import json
import unittest
from unittest.mock import MagicMock, patch

from dify_plugin.errors.model import CredentialsValidateFailedError

from models.llm.llm import THE_SYS_ENDPOINT_URL, ThesysLargeLanguageModel


class TestValidateCredentials(unittest.TestCase):
    def setUp(self) -> None:
        self.model = ThesysLargeLanguageModel(model_schemas=[])
        self.base_credentials = {
            "api_key": "test-key",
        }

    @staticmethod
    def _make_response(status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.text = text if text is not None else json.dumps(payload or {})
        if payload is not None:
            response.json.return_value = payload
        return response

    @patch("models.llm.llm.requests.post")
    def test_validation_accepts_201_success_response(self, mock_post: MagicMock) -> None:
        payload = {
            "id": "chatcmpl-thesys",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_post.return_value = self._make_response(201, payload=payload)

        self.model.validate_credentials("c1/openai/gpt-5/v-20251230", self.base_credentials)

        call_url = mock_post.call_args.args[0]
        self.assertEqual(call_url, f"{THE_SYS_ENDPOINT_URL}/chat/completions")

    @patch("models.llm.llm.requests.post")
    @patch.object(ThesysLargeLanguageModel, "_retry_with_safe_min_tokens")
    def test_validation_retries_with_max_completion_tokens(self, mock_retry: MagicMock, mock_post: MagicMock) -> None:
        mock_post.return_value = self._make_response(
            400,
            text="Invalid 'max_output_tokens': integer_below_min_value",
        )

        self.model.validate_credentials("c1/openai/gpt-5/v-20251230", self.base_credentials)

        mock_retry.assert_called_once()

    @patch("models.llm.llm.requests.post")
    @patch.object(ThesysLargeLanguageModel, "_retry_with_thinking_disabled")
    def test_validation_retries_with_thinking_disabled(self, mock_retry: MagicMock, mock_post: MagicMock) -> None:
        mock_post.return_value = self._make_response(
            400,
            text="thinking parameter is required for this model",
        )

        self.model.validate_credentials("c1/openai/gpt-5/v-20251230", self.base_credentials)

        mock_retry.assert_called_once()

    @patch("models.llm.llm.requests.post")
    def test_validation_raises_on_unrelated_error(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._make_response(400, text="invalid api key")

        with self.assertRaises(CredentialsValidateFailedError):
            self.model.validate_credentials("c1/openai/gpt-5/v-20251230", self.base_credentials)
