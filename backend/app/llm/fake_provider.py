import re

from app.domain.scenarios.models import Confidence, Reliability

from .models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    NormalizedAssessment,
    ResponseCertainty,
    RoleResponse,
    RoleResponseRequest,
    StakeholderMessageRequest,
    StakeholderMessageResponse,
)


class FakeLLMProvider:
    """Deterministic provider used by local development and tests."""

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        evidence = [*request.permitted_observations, *request.permitted_findings]
        if not evidence:
            return RoleResponse(
                message="I don't currently have enough verified information to answer that.",
                referenced_evidence_ids=[],
                certainty=ResponseCertainty.UNKNOWN,
            )

        order = {
            Reliability.LOW: 0,
            Reliability.MEDIUM: 1,
            Reliability.HIGH: 2,
            Reliability.CONFIRMED: 3,
        }
        reliability = min(
            evidence, key=lambda item: order[item.reliability]
        ).reliability.value
        return RoleResponse(
            message="Based on what I currently know: "
            + " ".join(item.statement for item in evidence),
            referenced_evidence_ids=[item.id for item in evidence],
            certainty=ResponseCertainty(reliability),
        )

    async def generate_stakeholder_message(
        self, request: StakeholderMessageRequest
    ) -> StakeholderMessageResponse:
        objective = request.objective.casefold()
        if "what evidence" in objective or "confirm" in objective:
            message = (
                "You described this as confirmed. What evidence demonstrates that "
                "the conclusion is confirmed rather than still suspected?"
            )
        elif "personal data" in objective:
            message = (
                "I need to assess our privacy exposure. What personal data may be "
                "affected, and what remains unknown?"
            )
        elif "restore" in objective or "preserv" in objective:
            message = (
                "Service disruption is creating operational pressure. What can we "
                "restore now without compromising the SOC's need to preserve evidence?"
            )
        elif "exfiltration" in objective or "executive" in objective:
            message = (
                "I need a concise executive update on possible data exfiltration. "
                "What is known, what is suspected, and what is the business impact?"
            )
        else:
            message = (
                f"I need an update on this objective: {request.objective.strip()} "
                "What is known, and what remains uncertain?"
            )
        return StakeholderMessageResponse(message=message)

    async def interpret_investigation(
        self, request: InvestigationInterpretationRequest
    ) -> InvestigationInterpretation:
        query = request.trainee_request.casefold()
        query_tokens = self._tokens(query)
        ranked: list[tuple[int, str]] = []
        for item in request.eligible_investigations:
            phrases = [item.label, item.request_description, *item.match_hints]
            exact = any(phrase.casefold() in query for phrase in phrases)
            candidate_tokens = set().union(*(self._tokens(phrase) for phrase in phrases))
            score = len(query_tokens & candidate_tokens)
            if exact:
                score += 100
            ranked.append((score, item.id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        if not ranked or ranked[0][0] < 2:
            return InvestigationInterpretation(
                matched=False,
                reason="No available investigation clearly matches the request.",
            )
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return InvestigationInterpretation(
                matched=False,
                reason="The request matches more than one available investigation.",
            )
        return InvestigationInterpretation(
            matched=True,
            investigation_id=ranked[0][1],
            reason="Matched to the closest available investigation.",
        )

    async def interpret_assessment(
        self, request: AssessmentInterpretationRequest
    ) -> AssessmentInterpretation:
        statement = request.trainee_statement.casefold()
        statement_tokens = self._tokens(statement)
        confidence = self._confidence(statement)
        known_ids = {
            item.id for item in [*request.known_observations, *request.known_findings]
        }
        basis = sorted(
            evidence_id
            for evidence_id in known_ids
            if evidence_id.casefold() in statement
        )
        assessments: list[NormalizedAssessment] = []
        for hypothesis in request.hypotheses:
            aliases = [hypothesis.key.replace("_", " "), hypothesis.label]
            matches = any(
                phrase.casefold() in statement
                or len(statement_tokens & self._tokens(phrase)) >= 2
                for phrase in aliases
            )
            if matches:
                assessments.append(
                    NormalizedAssessment(
                        hypothesis_id=hypothesis.id,
                        confidence=confidence,
                        basis_evidence_ids=basis,
                    )
                )
        return AssessmentInterpretation(assessments=assessments)

    @staticmethod
    def _tokens(value: str) -> set[str]:
        stop = {
            "a", "an", "and", "for", "from", "in", "of", "on", "or", "the",
            "to", "with", "check", "investigate", "review",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if len(token) > 2 and token not in stop
        }

    @staticmethod
    def _confidence(value: str) -> Confidence:
        if any(word in value for word in ("confirmed", "certain", "definitely")):
            return Confidence.CONFIRMED
        if any(word in value for word in ("high confidence", "very likely", "strongly")):
            return Confidence.HIGH
        if any(word in value for word in ("low confidence", "possibly", "unlikely")):
            return Confidence.LOW
        return Confidence.MEDIUM
