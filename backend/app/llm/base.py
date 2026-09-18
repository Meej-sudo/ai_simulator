from collections.abc import AsyncIterator
from typing import Protocol

from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    RoleResponse,
    RoleResponseRequest,
    StakeholderMessageRequest,
    StakeholderMessageResponse,
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

    async def generate_stakeholder_message(
        self, request: StakeholderMessageRequest
    ) -> StakeholderMessageResponse:
        ...


class StreamingLLMProvider(Protocol):
    def stream_role_response(
        self, request: RoleResponseRequest
    ) -> AsyncIterator[str]:
        """Yield raw structured-response fragments from the provider."""
        ...
