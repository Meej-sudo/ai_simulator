from openai import AsyncOpenAI

from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    RoleResponse,
    RoleResponseRequest,
)
from .prompts import (
    build_assessment_prompt,
    build_investigation_prompt,
    build_system_prompt,
)


class OpenAILLMProvider:
    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def _parse(self, system: str, user: str, output_type):
        result = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=output_type,
            store=False,
        )
        if result.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured response")
        return result.output_parsed

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        return await self._parse(
            build_system_prompt(request),
            request.trainee_question,
            RoleResponse,
        )

    async def interpret_investigation(
        self, request: InvestigationInterpretationRequest
    ) -> InvestigationInterpretation:
        return await self._parse(
            build_investigation_prompt(request),
            request.trainee_request,
            InvestigationInterpretation,
        )

    async def interpret_assessment(
        self, request: AssessmentInterpretationRequest
    ) -> AssessmentInterpretation:
        return await self._parse(
            build_assessment_prompt(request),
            request.trainee_statement,
            AssessmentInterpretation,
        )
