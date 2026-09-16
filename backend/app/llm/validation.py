from .base import LLMProvider
from .errors import LLMProviderError
from .models import (
    ResponseCertainty,
    RoleResponse,
    RoleResponseRequest,
    ValidatedRoleResponse,
)


SAFE_FALLBACK = RoleResponse(
    message="I don't currently have enough verified information to answer that.",
    referenced_fact_ids=[],
    certainty=ResponseCertainty.UNKNOWN,
)


class ConstrainedRoleResponder:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def generate(self, request: RoleResponseRequest) -> ValidatedRoleResponse:
        return await self._generate(request, use_provider_stream=False)

    async def generate_streamed(
        self, request: RoleResponseRequest
    ) -> ValidatedRoleResponse:
        return await self._generate(request, use_provider_stream=True)

    async def _generate(
        self,
        request: RoleResponseRequest,
        *,
        use_provider_stream: bool,
    ) -> ValidatedRoleResponse:
        allowed = {fact.id for fact in request.permitted_facts}
        violations: list[dict[str, object]] = []
        attempt_request = request

        for attempt in (1, 2):
            response = await self._provider_response(
                attempt_request,
                use_provider_stream=use_provider_stream,
            )
            unauthorized = sorted(set(response.referenced_fact_ids) - allowed)
            exposed_ids = sorted(fact_id for fact_id in allowed if fact_id in response.message)
            if not unauthorized and not exposed_ids:
                return ValidatedRoleResponse(response=response, violations=violations)

            violation = {
                "attempt": attempt,
                "unauthorized_fact_ids": unauthorized,
                "exposed_internal_fact_ids": exposed_ids,
            }
            violations.append(violation)
            attempt_request = request.model_copy(
                update={
                    "retry_instruction": (
                        "Your previous output violated the knowledge boundary. Use only the supplied "
                        "fact IDs in referenced_fact_ids and never place any internal ID in the message."
                    )
                }
            )

        return ValidatedRoleResponse(response=SAFE_FALLBACK, violations=violations)

    async def _provider_response(
        self,
        request: RoleResponseRequest,
        *,
        use_provider_stream: bool,
    ) -> RoleResponse:
        stream = getattr(self.provider, "stream_role_response", None)
        if not use_provider_stream or not callable(stream):
            return await self.provider.generate_role_response(request)

        fragments: list[str] = []
        async for fragment in stream(request):
            fragments.append(fragment)
        try:
            return RoleResponse.model_validate_json("".join(fragments))
        except ValueError as exc:
            raise LLMProviderError(
                "The LLM provider returned an invalid structured streaming response"
            ) from exc
