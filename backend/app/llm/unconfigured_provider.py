from .errors import LLMProviderError
from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    RoleResponse,
    RoleResponseRequest,
)


UNCONFIGURED_MESSAGE = (
    "No AI model is configured. Select a provider and model before "
    "starting an exercise."
)


class UnconfiguredLLMProvider:
    """Rejects LLM prompts until an administrator selects an AI model."""

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        raise LLMProviderError(UNCONFIGURED_MESSAGE)

    async def interpret_investigation(
        self, request: InvestigationInterpretationRequest
    ) -> InvestigationInterpretation:
        raise LLMProviderError(UNCONFIGURED_MESSAGE)

    async def interpret_assessment(
        self, request: AssessmentInterpretationRequest
    ) -> AssessmentInterpretation:
        raise LLMProviderError(UNCONFIGURED_MESSAGE)
