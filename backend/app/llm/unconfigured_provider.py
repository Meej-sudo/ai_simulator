from .errors import LLMProviderError
from .models import RoleResponse, RoleResponseRequest


class UnconfiguredLLMProvider:
    """Rejects role prompts until an administrator selects an AI model."""

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        raise LLMProviderError(
            "No AI model is configured. Select a provider and model before "
            "starting an exercise."
        )
