import logging
from collections.abc import Mapping

from dify_plugin import ModelProvider
from dify_plugin.entities.model import ModelType
from dify_plugin.errors.model import CredentialsValidateFailedError

logger = logging.getLogger(__name__)

DEFAULT_VALIDATE_MODEL = "c1/anthropic/claude-sonnet-4.6/v-20260331"


class ThesysProvider(ModelProvider):
    def validate_provider_credentials(self, credentials: Mapping) -> None:
        validate_model = credentials.get("validate_model") or DEFAULT_VALIDATE_MODEL
        llm_credentials = {
            "api_key": credentials.get("api_key"),
            "validate_model": validate_model,
        }

        try:
            model_instance = self.get_model_instance(ModelType.LLM)
            model_instance.validate_credentials(model=str(validate_model), credentials=llm_credentials)
        except CredentialsValidateFailedError:
            raise
        except Exception as ex:
            logger.exception("%s credentials validate failed", self.get_provider_schema().provider)
            raise ex
