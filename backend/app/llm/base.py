from collections.abc import AsyncIterator
from typing import Protocol

from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    RoleResponse,
    RoleResponseRequest,
)


class LLMProvider(Protocol):
    async def generate_role_response(
        self, request: RoleResponseRequest
    ) -> RoleResponse:
        ...

    async def interpret_investigation(
        self, request: InvestigationInterpretationRequest
    ) -> InvestigationInterpretation:
        ...

    async def interpret_assessment(
        self, request: AssessmentInterpretationRequest
    ) -> AssessmentInterpretation:
        ...


class StreamingLLMProvider(Protocol):
    def stream_role_response(
        self, request: RoleResponseRequest
    ) -> AsyncIterator[str]:
        """Yield raw structured-response fragments from the provider."""
        ...
