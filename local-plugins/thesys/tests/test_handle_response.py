import json
import unittest
from unittest.mock import MagicMock

from dify_plugin.entities.model.message import UserPromptMessage

from models.llm.llm import ThesysLargeLanguageModel


class TestHandleGenerateStreamResponse(unittest.TestCase):
    def setUp(self) -> None:
        self.model = ThesysLargeLanguageModel(model_schemas=[])
        self.credentials = {
            "api_key": "test-key",
        }
        self.prompt_messages = [UserPromptMessage(content="ping")]

    @staticmethod
    def _make_streaming_response(payloads: list[str]) -> MagicMock:
        response = MagicMock()
        response.iter_lines.return_value = payloads
        response.encoding = "utf-8"
        return response

    def test_stream_handler_accepts_one_shot_chat_completion_body(self) -> None:
        payload = {
            "id": "chatcmpl-thesys",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "<content thesys=\"true\">hello</content>",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 1,
                "total_tokens": 4,
            },
        }
        response = self._make_streaming_response([json.dumps(payload)])

        chunks = list(
            self.model._handle_generate_stream_response(
                model="c1/openai/gpt-5/v-20251230",
                credentials=self.model._apply_model_defaults("c1/openai/gpt-5/v-20251230", self.credentials),
                response=response,
                prompt_messages=self.prompt_messages,
            )
        )

        assert len(chunks) == 2
        assert chunks[0].delta.message.content == "<content thesys=\"true\">hello</content>"
        assert chunks[-1].delta.message.content == ""

    def test_stream_handler_parses_sse_chunk_with_id_prefix(self) -> None:
        payload = "\n".join([
            "id: 1",
            "event: message",
            (
                "data: {\"object\":\"chat.completion.chunk\","
                "\"choices\":[{\"index\":0,\"delta\":{\"content\":\"hi\"},"
                "\"finish_reason\":null}],"
                "\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}"
            ),
        ])
        response = self._make_streaming_response([payload, "data: [DONE]"])

        chunks = list(
            self.model._handle_generate_stream_response(
                model="c1/openai/gpt-5/v-20251230",
                credentials=self.model._apply_model_defaults("c1/openai/gpt-5/v-20251230", self.credentials),
                response=response,
                prompt_messages=self.prompt_messages,
            )
        )

        assert chunks[0].delta.message.content == "hi"
