from typing import TypeVar

import httpx
from pydantic import BaseModel

from .errors import LLMProviderError
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


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


class OllamaLLMProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 300,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def _chat(
        self,
        system_prompt: str,
        user_message: str,
        response_type: type[StructuredResponse],
        contract_name: str,
    ) -> StructuredResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "format": response_type.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0.2},
        }

        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
            else:
                response = await self.client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Ollama request timed out after {self.timeout_seconds:g} seconds"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc

        try:
            content = response.json()["message"]["content"]
            return response_type.model_validate_json(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                f"Ollama returned an invalid structured {contract_name}"
            ) from exc

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        return await self._chat(
            build_system_prompt(request),
            request.trainee_question,
            RoleResponse,
            "role response",
        )

    async def interpret_investigation(
        self, request: InvestigationInterpretationRequest
    ) -> InvestigationInterpretation:
        return await self._chat(
            build_investigation_prompt(request),
            request.trainee_request,
            InvestigationInterpretation,
            "investigation interpretation",
        )

    async def interpret_assessment(
        self, request: AssessmentInterpretationRequest
    ) -> AssessmentInterpretation:
        return await self._chat(
            build_assessment_prompt(request),
            request.trainee_statement,
            AssessmentInterpretation,
            "assessment interpretation",
        )
