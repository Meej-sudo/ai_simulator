import re
from collections.abc import Callable

from .base import LLMProvider
from .errors import LLMProviderError
from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    ResponseCertainty,
    RoleResponse,
    RoleResponseRequest,
    ValidatedAssessmentInterpretation,
    ValidatedInvestigationInterpretation,
    ValidatedRoleResponse,
)


# Internal evidence IDs must never appear in prose shown to the trainee.
INTERNAL_EVIDENCE_ID = re.compile(r"\b(?:O|FD)[0-9]+\b")

_JSON_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def partial_message(buffer: str) -> str:
    """Decode as much of the "message" field as the partial JSON already holds.

    The provider streams one JSON object, so its prose cannot be read with a
    normal parser until the object closes. This walks the string value itself
    and stops cleanly at the end of the buffer, at an incomplete escape, or at
    the closing quote.
    """
    key = buffer.find('"message"')
    if key == -1:
        return ""
    colon = buffer.find(":", key + len('"message"'))
    if colon == -1:
        return ""
    index = colon + 1
    while index < len(buffer) and buffer[index] in " \t\r\n":
        index += 1
    if index >= len(buffer) or buffer[index] != '"':
        return ""

    decoded: list[str] = []
    index += 1
    while index < len(buffer):
        character = buffer[index]
        if character == '"':
            break
        if character != "\\":
            decoded.append(character)
            index += 1
            continue
        if index + 1 >= len(buffer):
            break
        escape = buffer[index + 1]
        if escape == "u":
            if index + 6 > len(buffer):
                break
            decoded.append(chr(int(buffer[index + 2 : index + 6], 16)))
            index += 6
            continue
        decoded.append(_JSON_ESCAPES.get(escape, escape))
        index += 2
    return "".join(decoded)


SAFE_ROLE_FALLBACK = RoleResponse(
    message="I don't currently have enough verified information to answer that.",
    referenced_evidence_ids=[],
    certainty=ResponseCertainty.UNKNOWN,
)
SAFE_INVESTIGATION_FALLBACK = InvestigationInterpretation(
    matched=False,
    reason="The request could not be matched to an available investigation.",
)
SAFE_ASSESSMENT_FALLBACK = AssessmentInterpretation(assessments=[])


class ConstrainedRoleResponder:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def generate(self, request: RoleResponseRequest) -> ValidatedRoleResponse:
        return await self._generate(request, use_provider_stream=False)

    async def generate_streamed(
        self,
        request: RoleResponseRequest,
        on_delta: Callable[[str], None] | None = None,
    ) -> ValidatedRoleResponse:
        return await self._generate(
            request,
            use_provider_stream=True,
            on_delta=on_delta,
        )

    async def _generate(
        self,
        request: RoleResponseRequest,
        *,
        use_provider_stream: bool,
        on_delta: Callable[[str], None] | None = None,
    ) -> ValidatedRoleResponse:
        allowed = {
            item.id
            for item in [*request.permitted_observations, *request.permitted_findings]
        }
        violations: list[dict[str, object]] = []
        attempt_request = request

        for attempt in (1, 2):
            response = await self._provider_response(
                attempt_request,
                use_provider_stream=use_provider_stream,
                # Only the first attempt is released as it arrives. A retry
                # replaces what was shown rather than appending to it.
                on_delta=on_delta if attempt == 1 else None,
            )
            unauthorized = sorted(set(response.referenced_evidence_ids) - allowed)
            exposed_ids = sorted(set(INTERNAL_EVIDENCE_ID.findall(response.message)))
            if not unauthorized and not exposed_ids:
                return ValidatedRoleResponse(response=response, violations=violations)
            violations.append(
                {
                    "contract": "role_response",
                    "attempt": attempt,
                    "unauthorized_evidence_ids": unauthorized,
                    "exposed_internal_evidence_ids": exposed_ids,
                }
            )
            attempt_request = request.model_copy(
                update={
                    "retry_instruction": (
                        "Use only supplied evidence IDs in referenced_evidence_ids and "
                        "never place an internal ID in the message."
                    )
                }
            )

        return ValidatedRoleResponse(
            response=SAFE_ROLE_FALLBACK,
            violations=violations,
        )

    async def _provider_response(
        self,
        request: RoleResponseRequest,
        *,
        use_provider_stream: bool,
        on_delta: Callable[[str], None] | None = None,
    ) -> RoleResponse:
        stream = getattr(self.provider, "stream_role_response", None)
        if not use_provider_stream or not callable(stream):
            response = await self.provider.generate_role_response(request)
            if on_delta is not None:
                # Providers without a stream still deliver their reply in one
                # piece, so the caller sees the same delta contract.
                on_delta(response.message)
            return response

        buffer = ""
        released = 0
        releasing = on_delta is not None
        async for fragment in stream(request):
            buffer += fragment
            if not releasing:
                continue
            text = partial_message(buffer)
            if len(text) <= released:
                continue
            # An internal ID in the prose means this reply will be rejected and
            # retried, so stop releasing it and let the retry replace it. Only
            # the letters of an ID can have been released already: a single
            # digit is enough for this to match.
            if INTERNAL_EVIDENCE_ID.search(text):
                releasing = False
                continue
            on_delta(text[released:])
            released = len(text)
        try:
            return RoleResponse.model_validate_json(buffer)
        except ValueError as exc:
            raise LLMProviderError(
                "The LLM provider returned an invalid structured streaming response"
            ) from exc


class ConstrainedInvestigationInterpreter:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def interpret(
        self, request: InvestigationInterpretationRequest
    ) -> ValidatedInvestigationInterpretation:
        allowed = {item.id for item in request.eligible_investigations}
        violations: list[dict[str, object]] = []
        attempt_request = request

        for attempt in (1, 2):
            response = await self.provider.interpret_investigation(attempt_request)
            unauthorized = (
                response.investigation_id
                if response.investigation_id not in allowed
                else None
            )
            if unauthorized is None:
                return ValidatedInvestigationInterpretation(
                    response=response,
                    violations=violations,
                )
            violations.append(
                {
                    "contract": "investigation_interpretation",
                    "attempt": attempt,
                    "unauthorized_investigation_id": unauthorized,
                }
            )
            attempt_request = request.model_copy(
                update={
                    "retry_instruction": (
                        "The selected investigation was not eligible. Select only an ID "
                        "from the supplied list or return matched=false."
                    )
                }
            )

        return ValidatedInvestigationInterpretation(
            response=SAFE_INVESTIGATION_FALLBACK,
            violations=violations,
        )


class ConstrainedAssessmentInterpreter:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def interpret(
        self, request: AssessmentInterpretationRequest
    ) -> ValidatedAssessmentInterpretation:
        allowed_hypotheses = {item.id for item in request.hypotheses}
        allowed_evidence = {
            item.id
            for item in [*request.known_observations, *request.known_findings]
        }
        violations: list[dict[str, object]] = []
        attempt_request = request

        for attempt in (1, 2):
            response = await self.provider.interpret_assessment(attempt_request)
            hypothesis_ids = [item.hypothesis_id for item in response.assessments]
            unauthorized_hypotheses = sorted(
                set(hypothesis_ids) - allowed_hypotheses
            )
            unauthorized_evidence = sorted(
                {
                    evidence_id
                    for item in response.assessments
                    for evidence_id in item.basis_evidence_ids
                    if evidence_id not in allowed_evidence
                }
            )
            duplicates = sorted(
                {
                    item
                    for item in hypothesis_ids
                    if hypothesis_ids.count(item) > 1
                }
            )
            if not unauthorized_hypotheses and not unauthorized_evidence and not duplicates:
                return ValidatedAssessmentInterpretation(
                    response=response,
                    violations=violations,
                )
            violations.append(
                {
                    "contract": "assessment_interpretation",
                    "attempt": attempt,
                    "unauthorized_hypothesis_ids": unauthorized_hypotheses,
                    "unauthorized_evidence_ids": unauthorized_evidence,
                    "duplicate_hypothesis_ids": duplicates,
                }
            )
            attempt_request = request.model_copy(
                update={
                    "retry_instruction": (
                        "Use only supplied hypothesis and evidence IDs, with at most one "
                        "assessment per hypothesis."
                    )
                }
            )

        return ValidatedAssessmentInterpretation(
            response=SAFE_ASSESSMENT_FALLBACK,
            violations=violations,
        )
