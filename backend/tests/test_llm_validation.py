from app.domain.scenarios.models import CommunicationStyle, FactDefinition
from app.llm.models import ResponseCertainty, RoleResponse, RoleResponseRequest
from app.llm.validation import ConstrainedRoleResponder


class LeakingProvider:
    async def generate_role_response(self, request):
        return RoleResponse(
            message="An additional fact exists.",
            referenced_fact_ids=["F999"],
            certainty=ResponseCertainty.CONFIRMED,
        )


async def test_retries_once_then_returns_safe_fallback():
    request = RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        simulation_time=10,
        permitted_facts=[
            FactDefinition(
                id="F001",
                type="observation",
                statement="A failed login was observed.",
                confidence="confirmed",
            )
        ],
        confidence_semantics={"confirmed": "established fact"},
        trainee_question="What happened?",
    )

    result = await ConstrainedRoleResponder(LeakingProvider()).generate(request)

    assert len(result.violations) == 2
    assert result.response.referenced_fact_ids == []
    assert result.response.certainty == ResponseCertainty.UNKNOWN
