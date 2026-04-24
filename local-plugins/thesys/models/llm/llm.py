import codecs
import json
import re
from collections.abc import Generator, Mapping
from contextlib import suppress
from typing import Any
from urllib.parse import urljoin

import requests
from dify_plugin.entities import I18nObject
from dify_plugin.entities.model import (
    AIModelEntity,
    DefaultParameterName,
    ModelFeature,
    ParameterRule,
    ParameterType,
)
from dify_plugin.entities.model.llm import LLMMode, LLMResult, LLMResultChunk, LLMResultChunkDelta
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    PromptMessage,
    PromptMessageFunction,
    PromptMessageRole,
    PromptMessageTool,
    SystemPromptMessage,
)
from dify_plugin.errors.model import CredentialsValidateFailedError, InvokeError
from dify_plugin.interfaces.model.openai_compatible.llm import OAICompatLargeLanguageModel, _increase_tool_call
from pydantic import TypeAdapter, ValidationError

THE_SYS_ENDPOINT_URL = "https://api.thesys.dev/v1/embed"
DEFAULT_VALIDATE_MODEL = "c1/anthropic/claude-sonnet-4.6/v-20260331"


def _extract_sse_data_payload(chunk: str) -> str:
    data_lines: list[str] = []
    for raw_line in chunk.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
            continue
        if line.startswith(("id:", "event:", "retry:")):
            continue
        if not data_lines:
            data_lines.append(line)

    if data_lines:
        return "\n".join(data_lines)

    return chunk.strip().removeprefix("data:").lstrip()


class ThesysLargeLanguageModel(OAICompatLargeLanguageModel):
    _THINK_PATTERN = re.compile(r"^<think>.*?</think>\s*", re.DOTALL)
    _NEEDS_MAX_COMPLETION_TOKENS_PATTERN = re.compile(r"^(o1|o3|gpt-5)", re.IGNORECASE)
    # Credential validation sends a 1-token ping. A 30s read budget is generous
    # for that and avoids tying up the UI for minutes on a bad endpoint.
    _VALIDATE_TIMEOUT = (10, 30)
    # Hard cap the thinking-filter buffer so a malformed stream that opens
    # `<think>` without ever closing it cannot grow memory unbounded.
    _MAX_THINKING_BUFFER_CHARS = 64 * 1024

    @classmethod
    def _apply_model_defaults(
        cls,
        model: str,
        credentials: Mapping[str, Any] | dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(credentials)
        merged["endpoint_url"] = THE_SYS_ENDPOINT_URL
        merged["mode"] = "chat"
        merged.setdefault("stream_mode_delimiter", "\n\n")
        merged.setdefault("token_param_name", "auto")
        merged.setdefault("compatibility_mode", "strict")
        merged.setdefault("function_calling_type", "no_call")
        merged.setdefault("vision_support", "no_support")
        merged.setdefault("structured_output_support", "supported")
        merged.setdefault("agent_thought_support", "supported")
        merged.setdefault("stream_mode_auth", "not_use")
        merged.setdefault("validate_model", DEFAULT_VALIDATE_MODEL)
        merged.setdefault("endpoint_model_name", model)
        return merged

    @staticmethod
    def _needs_max_completion_tokens(model: str) -> bool:
        return bool(ThesysLargeLanguageModel._NEEDS_MAX_COMPLETION_TOKENS_PATTERN.match(model))

    @staticmethod
    def _is_success_status(status_code: int) -> bool:
        return 200 <= status_code < 300

    @staticmethod
    def _raise_credentials_error(response: requests.Response) -> None:
        raise CredentialsValidateFailedError(
            "Credentials validation failed with status code "
            f"{response.status_code} and response body {response.text}"
        )

    @staticmethod
    def _normalize_validation_response_object(
        json_result: dict[str, Any],
        completion_type: LLMMode,
    ) -> None:
        if completion_type is LLMMode.CHAT and json_result.get("object", "") == "":
            json_result["object"] = "chat.completion"

    def _validate_ping_response_payload(self, response: requests.Response, completion_type: LLMMode) -> None:
        try:
            json_result = response.json()
        except json.JSONDecodeError as ex:
            raise CredentialsValidateFailedError(
                f"Credentials validation failed: JSON decode error, response body {response.text}"
            ) from ex

        self._normalize_validation_response_object(json_result, completion_type)
        if completion_type is LLMMode.CHAT and json_result.get("object") != "chat.completion":
            raise CredentialsValidateFailedError(
                "Credentials validation failed: invalid response object, "
                f"must be 'chat.completion', response body {response.text}"
            )

    def validate_credentials(self, model: str, credentials: dict) -> None:
        credentials = self._apply_model_defaults(model, credentials)
        validate_model = str(credentials.get("validate_model") or DEFAULT_VALIDATE_MODEL)
        credentials["endpoint_model_name"] = validate_model

        param_pref = credentials.get("token_param_name", "auto")
        if param_pref == "max_completion_tokens" or (
            param_pref == "auto" and self._needs_max_completion_tokens(validate_model)
        ):
            self._retry_with_safe_min_tokens(validate_model, credentials)
            return

        response: requests.Response | None = None
        try:
            headers = {"Content-Type": "application/json"}
            api_key = credentials.get("api_key")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            endpoint_url = urljoin(
                f"{credentials['endpoint_url'].rstrip('/')}/",
                "chat/completions",
            )
            validate_credentials_max_tokens = credentials.get("validate_credentials_max_tokens", 5) or 5
            data = {
                "model": validate_model,
                "max_tokens": validate_credentials_max_tokens,
                "messages": [{"role": "user", "content": "ping"}],
            }

            response = requests.post(
                endpoint_url,
                headers=headers,
                json=data,
                timeout=self._VALIDATE_TIMEOUT,
            )
            if not self._is_success_status(response.status_code):
                self._raise_credentials_error(response)

            self._validate_ping_response_payload(response, LLMMode.CHAT)
        except CredentialsValidateFailedError as ex:
            message = str(ex)
            if (
                "Invalid 'max_output_tokens'" in message
                or "integer_below_min_value" in message
            ):
                self._retry_with_safe_min_tokens(validate_model, credentials)
                return
            if "budget_tokens" in message or "thinking" in message:
                self._retry_with_thinking_disabled(validate_model, credentials)
                return
            raise
        except Exception as ex:
            if response is not None:
                raise CredentialsValidateFailedError(
                    f"An error occurred during credentials validation: {ex!s}, response body {response.text}"
                ) from ex
            raise CredentialsValidateFailedError(f"An error occurred during credentials validation: {ex!s}") from ex

    def _retry_with_safe_min_tokens(self, model: str, credentials: dict) -> None:
        endpoint_url = urljoin(
            f"{credentials['endpoint_url'].rstrip('/')}/",
            "chat/completions",
        )
        headers = {"Content-Type": "application/json"}
        api_key = credentials.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = {
            "model": credentials.get("endpoint_model_name", model),
            "messages": [{"role": "user", "content": "ping"}],
            "max_completion_tokens": 16,
        }

        response = requests.post(
            endpoint_url,
            headers=headers,
            json=data,
            timeout=self._VALIDATE_TIMEOUT,
        )
        if not self._is_success_status(response.status_code):
            self._raise_credentials_error(response)

    def _retry_with_thinking_disabled(self, model: str, credentials: dict) -> None:
        endpoint_url = urljoin(
            f"{credentials['endpoint_url'].rstrip('/')}/",
            "chat/completions",
        )
        headers = {"Content-Type": "application/json"}
        api_key = credentials.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = {
            "model": credentials.get("endpoint_model_name", model),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": int(credentials.get("validate_credentials_max_tokens", 5) or 5),
            "thinking": {"type": "disabled"},
        }

        response = requests.post(
            endpoint_url,
            headers=headers,
            json=data,
            timeout=self._VALIDATE_TIMEOUT,
        )
        if not self._is_success_status(response.status_code):
            self._raise_credentials_error(response)

    def get_customizable_model_schema(self, model: str, credentials: Mapping | dict) -> AIModelEntity:
        normalized_credentials = self._apply_model_defaults(model, credentials)
        entity = super().get_customizable_model_schema(model, normalized_credentials)

        if normalized_credentials.get("structured_output_support", "supported") == "supported":
            entity.parameter_rules.append(
                ParameterRule(
                    name=DefaultParameterName.RESPONSE_FORMAT.value,
                    label=I18nObject(en_US="Response Format"),
                    help=I18nObject(en_US="Specify the format that the model must output."),
                    type=ParameterType.STRING,
                    options=["text", "json_object", "json_schema"],
                    required=False,
                )
            )
            entity.parameter_rules.append(
                ParameterRule(
                    name=DefaultParameterName.JSON_SCHEMA.value,
                    use_template=DefaultParameterName.JSON_SCHEMA.value,
                )
            )

        display_name = normalized_credentials.get("display_name")
        if display_name:
            entity.label = I18nObject(en_US=str(display_name))

        agent_thought_support = normalized_credentials.get("agent_thought_support", "supported")
        if (
            agent_thought_support in ["supported", "only_thinking_supported"]
            and ModelFeature.AGENT_THOUGHT not in entity.features
        ):
            entity.features.append(ModelFeature.AGENT_THOUGHT)

        if agent_thought_support == "supported":
            entity.parameter_rules.append(
                ParameterRule(
                    name="enable_thinking",
                    label=I18nObject(en_US="Thinking mode"),
                    help=I18nObject(en_US="Whether to enable thinking mode."),
                    type=ParameterType.BOOLEAN,
                    required=False,
                )
            )

        if agent_thought_support in ["supported", "only_thinking_supported"]:
            entity.parameter_rules.append(
                ParameterRule(
                    name="reasoning_effort",
                    label=I18nObject(en_US="Reasoning effort"),
                    help=I18nObject(en_US="Constrains effort on reasoning for reasoning models."),
                    type=ParameterType.STRING,
                    options=["low", "medium", "high"],
                    required=False,
                )
            )

        return entity

    @classmethod
    def _drop_analyze_channel(cls, prompt_messages: list[PromptMessage]) -> None:
        for prompt_message in prompt_messages:
            if not isinstance(prompt_message, AssistantPromptMessage):
                continue
            if not isinstance(prompt_message.content, str):
                continue
            if not prompt_message.content.startswith("<think>"):
                continue

            new_content = cls._THINK_PATTERN.sub("", prompt_message.content, count=1)
            if new_content != prompt_message.content:
                prompt_message.content = new_content

    def _wrap_thinking_by_reasoning_content(
        self,
        delta: dict[str, Any],
        is_reasoning: bool,
    ) -> tuple[str, bool]:
        reasoning_piece = delta.get("reasoning") or delta.get("reasoning_content")
        content_piece = delta.get("content") or ""

        if reasoning_piece:
            if not is_reasoning:
                output = f"<think>\n{reasoning_piece}"
                is_reasoning = True
            else:
                output = str(reasoning_piece)
        elif is_reasoning:
            is_reasoning = False
            output = f"\n</think>{content_piece}"
        else:
            output = content_piece

        return output, is_reasoning

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        credentials = self._apply_model_defaults(model, credentials)

        if model_parameters.get("response_format") == "json_schema":
            json_schema_str = model_parameters.get("json_schema")
            if json_schema_str:
                structured_output_prompt = (
                    "Your response must be a JSON object that validates against "
                    "the following JSON schema, and nothing else.\n"
                    f"JSON Schema: ```json\n{json_schema_str}\n```"
                )

                existing_system_prompt = next(
                    (
                        prompt_message
                        for prompt_message in prompt_messages
                        if prompt_message.role == PromptMessageRole.SYSTEM
                    ),
                    None,
                )
                if existing_system_prompt:
                    existing_system_prompt.content = (
                        structured_output_prompt
                        + "\n\n"
                        + str(existing_system_prompt.content)
                    )
                else:
                    prompt_messages.insert(0, SystemPromptMessage(content=structured_output_prompt))

        agent_thought_support = credentials.get("agent_thought_support", "supported")
        enable_thinking_value: bool | None = None
        if agent_thought_support == "only_thinking_supported":
            enable_thinking_value = True
        elif agent_thought_support == "not_supported":
            enable_thinking_value = False
        else:
            user_enable_thinking = model_parameters.pop("enable_thinking", None)
            if user_enable_thinking is not None:
                enable_thinking_value = bool(user_enable_thinking)

        if enable_thinking_value is not None:
            model_parameters["thinking"] = {"type": "enabled" if enable_thinking_value else "disabled"}
            model_parameters["enable_thinking"] = enable_thinking_value

        reasoning_effort_value = model_parameters.pop("reasoning_effort", None)
        if enable_thinking_value is True and reasoning_effort_value is not None:
            model_parameters["reasoning_effort"] = reasoning_effort_value

        with suppress(Exception):
            self._drop_analyze_channel(prompt_messages)

        param_pref = credentials.get("token_param_name", "auto")
        use_max_completion = (
            param_pref == "max_completion_tokens"
            or (param_pref == "auto" and self._needs_max_completion_tokens(model))
        )
        if use_max_completion and "max_completion_tokens" not in model_parameters and "max_tokens" in model_parameters:
            model_parameters["max_completion_tokens"] = model_parameters.pop("max_tokens")

        result = self._generate(model, credentials, prompt_messages, model_parameters, tools, stop, stream, user)
        if enable_thinking_value is False:
            if stream:
                return self._filter_thinking_stream(result)
            return self._filter_thinking_result(result)

        return result

    def _filter_thinking_result(self, result: LLMResult) -> LLMResult:
        if result.message and result.message.content:
            content = result.message.content
            if isinstance(content, str) and content.startswith("<think>"):
                filtered_content = self._THINK_PATTERN.sub("", content, count=1)
                if filtered_content != content:
                    result.message.content = filtered_content
        return result

    def _filter_thinking_stream(self, stream: Generator) -> Generator:
        buffer = ""
        in_thinking = False
        thinking_started = False

        for chunk in stream:
            if chunk.delta and chunk.delta.message and chunk.delta.message.content:
                content = chunk.delta.message.content
                buffer += content

                if not thinking_started and buffer.startswith("<think>"):
                    in_thinking = True
                    thinking_started = True

                if in_thinking and "</think>" in buffer:
                    end_index = buffer.find("</think>") + len("</think>")
                    while end_index < len(buffer) and buffer[end_index].isspace():
                        end_index += 1
                    buffer = buffer[end_index:]
                    in_thinking = False
                    thinking_started = False
                    if buffer:
                        chunk.delta.message.content = buffer
                        buffer = ""
                        yield chunk
                    continue

                if in_thinking and len(buffer) > self._MAX_THINKING_BUFFER_CHARS:
                    # The model opened `<think>` but never emitted `</think>`.
                    # Flush what we have buffered so far and stop trying to
                    # strip it, so the user still gets the content and memory
                    # does not grow unbounded.
                    chunk.delta.message.content = buffer
                    buffer = ""
                    in_thinking = False
                    thinking_started = False
                    yield chunk
                    continue

                if not in_thinking:
                    yield chunk
                    buffer = ""
            else:
                yield chunk

    def _handle_generate_response(
        self,
        model: str,
        credentials: dict,
        response: requests.Response,
        prompt_messages: list[PromptMessage],
    ) -> LLMResult:
        response_json: dict[str, Any] = response.json()
        choices = response_json.get("choices") or []
        if not choices:
            raise InvokeError("LLM response returned no choices")

        output = choices[0]
        message = output.get("message") or {}
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            response_content = raw_content
        elif raw_content is None:
            response_content = ""
        else:
            response_content = str(raw_content)

        assistant_message = AssistantPromptMessage(content=response_content, tool_calls=[])
        function_calling_type = credentials.get("function_calling_type", "no_call")
        if function_calling_type == "tool_call" and message.get("tool_calls"):
            assistant_message.tool_calls = self._extract_response_tool_calls(message["tool_calls"])
        elif function_calling_type == "function_call" and message.get("function_call"):
            function_call = self._extract_response_function_call(message["function_call"])
            assistant_message.tool_calls = [function_call] if function_call else []

        usage_payload = response_json.get("usage")
        if usage_payload:
            prompt_tokens = usage_payload["prompt_tokens"]
            completion_tokens = usage_payload["completion_tokens"]
        else:
            prompt_tokens = self._num_tokens_from_messages(prompt_messages, credentials=credentials)
            completion_tokens = self._num_tokens_from_string(assistant_message.content or "")

        usage = self._calc_response_usage(model, credentials, prompt_tokens, completion_tokens)
        return LLMResult(
            id=response_json.get("id"),
            model=response_json.get("model", model),
            message=assistant_message,
            usage=usage,
        )

    def _handle_generate_stream_response(
        self,
        model: str,
        credentials: dict,
        response: requests.Response,
        prompt_messages: list[PromptMessage],
    ) -> Generator:
        chunk_index = 0
        full_assistant_content = ""
        tools_calls: list[AssistantPromptMessage.ToolCall] = []
        finish_reason = None
        usage = None
        is_reasoning_started = False
        delimiter = codecs.decode(str(credentials.get("stream_mode_delimiter", "\n\n")), "unicode_escape")

        for chunk in response.iter_lines(decode_unicode=True, delimiter=delimiter):
            chunk = chunk.strip()
            if not chunk or chunk.startswith(":"):
                chunk_index += 1
                continue

            decoded_chunk = _extract_sse_data_payload(chunk)
            if decoded_chunk == "[DONE]":
                chunk_index += 1
                continue

            try:
                chunk_json: dict[str, Any] = TypeAdapter(dict[str, Any]).validate_json(decoded_chunk)
            except ValidationError:
                yield self._create_final_llm_result_chunk(
                    index=chunk_index + 1,
                    message=AssistantPromptMessage(content=""),
                    finish_reason="Non-JSON encountered.",
                    usage=usage,
                    model=model,
                    credentials=credentials,
                    prompt_messages=prompt_messages,
                    full_content=full_assistant_content,
                )
                break

            if chunk_json.get("error") and chunk_json.get("choices") is None:
                raise ValueError(chunk_json.get("error"))

            if parsed_usage := chunk_json.get("usage"):
                usage = parsed_usage

            choices = chunk_json.get("choices") or []
            if not choices:
                chunk_index += 1
                continue

            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            chunk_index += 1

            assistant_prompt_message: AssistantPromptMessage | None = None
            assistant_message_tool_calls = None

            if "delta" in choice:
                delta = choice["delta"]
                delta_content, is_reasoning_started = (
                    self._wrap_thinking_by_reasoning_content(
                        delta,
                        is_reasoning_started,
                    )
                )

                if "tool_calls" in delta and credentials.get("function_calling_type", "no_call") == "tool_call":
                    assistant_message_tool_calls = delta.get("tool_calls")
                elif (
                    "function_call" in delta
                    and credentials.get("function_calling_type", "no_call") == "function_call"
                ):
                    assistant_message_tool_calls = [
                        {"id": "tool_call_id", "type": "function", "function": delta.get("function_call", {})}
                    ]

                if assistant_message_tool_calls:
                    tool_calls = self._extract_response_tool_calls(assistant_message_tool_calls)
                    _increase_tool_call(tool_calls, tools_calls)

                if delta_content:
                    assistant_prompt_message = AssistantPromptMessage(content=delta_content)
                    full_assistant_content += delta_content
            elif "message" in choice:
                message = choice.get("message") or {}
                raw_content = message.get("content")
                if isinstance(raw_content, str):
                    message_content = raw_content
                elif raw_content is None:
                    message_content = ""
                else:
                    message_content = str(raw_content)

                if "tool_calls" in message and credentials.get("function_calling_type", "no_call") == "tool_call":
                    assistant_message_tool_calls = message.get("tool_calls")
                elif (
                    "function_call" in message
                    and credentials.get("function_calling_type", "no_call") == "function_call"
                ):
                    assistant_message_tool_calls = [
                        {"id": "tool_call_id", "type": "function", "function": message.get("function_call", {})}
                    ]

                if assistant_message_tool_calls:
                    tool_calls = self._extract_response_tool_calls(assistant_message_tool_calls)
                    _increase_tool_call(tool_calls, tools_calls)

                if message_content:
                    assistant_prompt_message = AssistantPromptMessage(content=message_content)
                    full_assistant_content += message_content

            if assistant_prompt_message is not None:
                yield LLMResultChunk(
                    model=model,
                    delta=LLMResultChunkDelta(
                        index=chunk_index,
                        message=assistant_prompt_message,
                    ),
                )

        if tools_calls:
            yield LLMResultChunk(
                model=model,
                delta=LLMResultChunkDelta(
                    index=chunk_index,
                    message=AssistantPromptMessage(tool_calls=tools_calls, content=""),
                ),
            )

        yield self._create_final_llm_result_chunk(
            index=chunk_index,
            message=AssistantPromptMessage(content=""),
            finish_reason=finish_reason,
            usage=usage,
            model=model,
            credentials=credentials,
            prompt_messages=prompt_messages,
            full_content=full_assistant_content,
        )

    def _generate(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        credentials = self._apply_model_defaults(model, credentials)
        headers = {
            "Content-Type": "application/json",
            "Accept-Charset": "utf-8",
        }
        api_key = credentials.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        endpoint_url = urljoin(
            f"{credentials['endpoint_url'].rstrip('/')}/",
            "chat/completions",
        )
        response_format = model_parameters.get("response_format")
        if response_format:
            if response_format == "json_schema":
                json_schema = model_parameters.get("json_schema")
                if not json_schema:
                    raise ValueError(
                        "Must define JSON Schema when the response format is json_schema"
                    )
                try:
                    schema = TypeAdapter(dict[str, Any]).validate_json(json_schema)
                except Exception as ex:
                    raise ValueError(f"not correct json_schema format: {json_schema}") from ex
                model_parameters.pop("json_schema")
                model_parameters["response_format"] = {
                    "type": "json_schema",
                    "json_schema": schema,
                }
            else:
                model_parameters["response_format"] = {"type": response_format}
        elif "json_schema" in model_parameters:
            del model_parameters["json_schema"]

        data = {
            "model": credentials.get("endpoint_model_name", model),
            "stream": stream,
            **model_parameters,
            "messages": [
                self._convert_prompt_message_to_dict(message, credentials)
                for message in prompt_messages
            ],
        }

        function_calling_type = credentials.get("function_calling_type", "no_call")
        if tools:
            if function_calling_type == "function_call":
                data["functions"] = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                    for tool in tools
                ]
            elif function_calling_type == "tool_call":
                data["tool_choice"] = "auto"
                data["tools"] = [
                    PromptMessageFunction(function=tool).model_dump()
                    for tool in tools
                ]

        if stop:
            data["stop"] = stop
        if user:
            data["user"] = user

        response = requests.post(
            endpoint_url,
            headers=headers,
            json=data,
            timeout=(10, 300),
            stream=stream,
        )

        if response.encoding is None or response.encoding == "ISO-8859-1":
            response.encoding = "utf-8"

        if not self._is_success_status(response.status_code):
            raise InvokeError(
                f"API request failed with status code {response.status_code}: {response.text}"
            )

        if stream:
            return self._handle_generate_stream_response(
                model,
                credentials,
                response,
                prompt_messages,
            )

        return self._handle_generate_response(model, credentials, response, prompt_messages)
