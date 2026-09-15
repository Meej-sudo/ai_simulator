import re

from .base import LLMProvider
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
        allowed = {
            item.id
            for item in [*request.permitted_observations, *request.permitted_findings]
        }
        violations: list[dict[str, object]] = []
        attempt_request = request

        for attempt in (1, 2):
            response = await self.provider.generate_role_response(attempt_request)
            unauthorized = sorted(set(response.referenced_evidence_ids) - allowed)
            exposed_ids = sorted(
                set(re.findall(r"\b(?:O|FD)[0-9]+\b", response.message))
            )
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
