from app.domain.scenarios.models import Confidence

from .models import ResponseCertainty, RoleResponse, RoleResponseRequest


class FakeLLMProvider:
    """Deterministic provider used by local development and tests."""

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        if not request.permitted_facts:
            return RoleResponse(
                message="I don't currently have enough verified information to answer that.",
                referenced_fact_ids=[],
                certainty=ResponseCertainty.UNKNOWN,
            )

        facts = request.permitted_facts
        statements = " ".join(fact.statement for fact in facts)
        order = {
            Confidence.LOW: 0,
            Confidence.MEDIUM: 1,
            Confidence.HIGH: 2,
            Confidence.CONFIRMED: 3,
        }
        certainty = min(facts, key=lambda fact: order[fact.confidence]).confidence.value
        return RoleResponse(
            message=f"Based on what I currently know: {statements}",
            referenced_fact_ids=[fact.id for fact in facts],
            certainty=ResponseCertainty(certainty),
        )
