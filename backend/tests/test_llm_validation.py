import json

from app.domain.scenarios.models import (
    CommunicationStyle,
    FindingDefinition,
    HypothesisDefinition,
    ObservationDefinition,
    PersonalityProfile,
    PersonalityTraits,
)
from app.llm.models import (
    AssessmentInterpretation,
    AssessmentInterpretationRequest,
    EligibleInvestigation,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    NormalizedAssessment,
    ResponseCertainty,
    RoleResponse,
    RoleResponseRequest,
)
from app.llm.validation import (
    ConstrainedAssessmentInterpreter,
    ConstrainedInvestigationInterpreter,
    ConstrainedRoleResponder,
)


class LeakingProvider:
    async def generate_role_response(self, request):
        return RoleResponse(
            message="An additional finding FD999 exists.",
            referenced_evidence_ids=["FD999"],
            certainty=ResponseCertainty.CONFIRMED,
        )

    async def interpret_investigation(self, request):
        return InvestigationInterpretation(
            matched=True,
            investigation_id="I999",
            reason="Invented.",
        )

    async def interpret_assessment(self, request):
        return AssessmentInterpretation(
            assessments=[
                NormalizedAssessment(
                    hypothesis_id="H999",
                    confidence="confirmed",
                    basis_evidence_ids=["FD999"],
                )
            ]
        )


class StreamingSafeProvider:
    async def generate_role_response(self, request):
        raise AssertionError("non-streaming provider method should not be used")

    async def stream_role_response(self, request):
        content = json.dumps(
            {
                "message": "**Confirmed:** A failed login was observed.",
                "referenced_evidence_ids": ["O001"],
                "certainty": "confirmed",
            }
        )
        yield content[:20]
        yield content[20:]


def observation() -> ObservationDefinition:
    return ObservationDefinition(
        id="O001",
        source="monitoring",
        statement="A failed login was observed.",
        reliability="high",
    )


def personality() -> PersonalityProfile:
    return PersonalityProfile(
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
    )


def role_request() -> RoleResponseRequest:
    return RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        personality=personality(),
        simulation_time=10,
        permitted_observations=[observation()],
        permitted_findings=[],
        trainee_question="What happened?",
    )


async def test_role_response_retries_once_then_returns_safe_fallback():
    request = role_request()

    result = await ConstrainedRoleResponder(LeakingProvider()).generate(request)

    assert len(result.violations) == 2
    assert result.response.referenced_evidence_ids == []
    assert result.response.certainty == ResponseCertainty.UNKNOWN


async def test_investigation_router_rejects_noneligible_id_after_retry():
    request = InvestigationInterpretationRequest(
        trainee_request="Inspect the destination.",
        performer_role="soc",
        eligible_investigations=[
            EligibleInvestigation(
                id="I004",
                label="Identify outbound destination",
                request_description="Determine where outbound traffic went.",
                match_hints=["outbound destination"],
            )
        ],
    )

    result = await ConstrainedInvestigationInterpreter(LeakingProvider()).interpret(
        request
    )

    assert len(result.violations) == 2
    assert result.response.matched is False
    assert result.response.investigation_id is None


async def test_assessment_rejects_unknown_hypothesis_and_hidden_evidence():
    request = AssessmentInterpretationRequest(
        trainee_statement="Exfiltration is confirmed.",
        actor_role="soc",
        hypotheses=[
            HypothesisDefinition(id="H002", key="data_exfiltration", label="Data exfiltration")
        ],
        known_observations=[observation()],
        known_findings=[
            FindingDefinition(
                id="FD004",
                statement="Destination is unapproved.",
                reliability="high",
            )
        ],
        confidence_semantics={"confirmed": "established or certain"},
    )

    result = await ConstrainedAssessmentInterpreter(LeakingProvider()).interpret(
        request
    )

    assert len(result.violations) == 2
    assert result.response.assessments == []


def test_interpreter_requests_contain_no_outcomes_or_ground_truth_fields():
    investigation = InvestigationInterpretationRequest(
        trainee_request="Inspect egress.",
        performer_role="soc",
        eligible_investigations=[],
    )
    assessment = AssessmentInterpretationRequest(
        trainee_statement="Exfiltration seems possible.",
        actor_role="soc",
        hypotheses=[],
        known_observations=[],
        known_findings=[],
        confidence_semantics={},
    )

    serialized = investigation.model_dump_json() + assessment.model_dump_json()

    assert "ground_truth" not in serialized
    assert "outcome" not in serialized
    assert "reveal_findings" not in serialized


async def test_streamed_provider_output_is_buffered_and_validated():
    request = role_request()

    result = await ConstrainedRoleResponder(StreamingSafeProvider()).generate_streamed(
        request
    )

    assert result.violations == []
    assert result.response.message.startswith("**Confirmed:**")
    assert result.response.referenced_evidence_ids == ["O001"]
