import json

from app.domain.scenarios.models import (
    CommunicationStyle,
    FactDefinition,
    PersonalityProfile,
    PersonalityTraits,
)
from app.llm.models import ResponseCertainty, RoleResponse, RoleResponseRequest
from app.llm.validation import ConstrainedRoleResponder


class LeakingProvider:
    async def generate_role_response(self, request):
        return RoleResponse(
            message="An additional fact exists.",
            referenced_fact_ids=["F999"],
            certainty=ResponseCertainty.CONFIRMED,
        )


class StreamingSafeProvider:
    async def generate_role_response(self, request):
        raise AssertionError("non-streaming provider method should not be used")

    async def stream_role_response(self, request):
        content = json.dumps(
            {
                "message": "**Confirmed:** A failed login was observed.",
                "referenced_fact_ids": ["F001"],
                "certainty": "confirmed",
            }
        )
        yield content[:20]
        yield content[20:]


async def test_retries_once_then_returns_safe_fallback():
    request = RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        personality=PersonalityProfile(
            summary="Calm and skeptical.",
            traits=PersonalityTraits(
                openness="high",
                conscientiousness="high",
                extraversion="low",
                agreeableness="medium",
                emotional_stability="high",
            ),
            behavioral_tendencies=["Lead with evidence."],
            under_pressure="Become more methodical.",
        ),
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


async def test_streamed_provider_output_is_buffered_and_validated():
    request = RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        personality=PersonalityProfile(
            summary="Calm and skeptical.",
            traits=PersonalityTraits(
                openness="high",
                conscientiousness="high",
                extraversion="low",
                agreeableness="medium",
                emotional_stability="high",
            ),
            behavioral_tendencies=["Lead with evidence."],
            under_pressure="Become more methodical.",
        ),
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

    result = await ConstrainedRoleResponder(StreamingSafeProvider()).generate_streamed(
        request
    )

    assert result.violations == []
    assert result.response.message.startswith("**Confirmed:**")
    assert result.response.referenced_fact_ids == ["F001"]
