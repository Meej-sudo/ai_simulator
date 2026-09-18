from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.scenarios.models import EventDefinition
from app.domain.simulation.event_engine import EventEngine, SessionState
from app.domain.simulation.models import EventSnapshot, EventType, InteractionStatus
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.scenario_registry import ScenarioRegistry
from app.services.simulation import SimulationService


SCENARIOS = Path(__file__).resolve().parents[2] / "content" / "scenarios"


class RecordingProvider(FakeLLMProvider):
    def __init__(self):
        self.stakeholder_requests = []

    async def generate_stakeholder_message(self, request):
        self.stakeholder_requests.append(request)
        return await super().generate_stakeholder_message(request)


def make_service(provider=None):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    return SimulationService(Session(engine), registry, provider or FakeLLMProvider())


async def started(service):
    session = service.create_session("ransomware_001", "track_alpha", seed=7)
    await service.start_async(session.id)
    return session


def test_event_engine_all_any_and_once_are_deterministic():
    service = make_service()
    scenario = service.scenarios.materialize("ransomware_001", "track_alpha")
    adapter = TypeAdapter(EventDefinition)
    all_event = adapter.validate_python({
        "id": "TEST_ALL",
        "type": "reveal_evidence",
        "trigger": {
            "type": "all",
            "triggers": [
                {"type": "simulation_time", "at_minute": 5},
                {"type": "evidence_known", "role_id": "soc", "evidence_id": "O001"},
            ],
        },
        "effects": [{"type": "reveal_observation", "role_id": "soc", "observation_id": "O002"}],
        "once": True,
    })
    any_event = adapter.validate_python({
        "id": "TEST_ANY",
        "type": "reveal_evidence",
        "trigger": {
            "type": "any",
            "triggers": [
                {"type": "simulation_time", "at_minute": 99},
                {"type": "evidence_known", "role_id": "soc", "evidence_id": "O001"},
            ],
        },
        "effects": [{"type": "reveal_observation", "role_id": "soc", "observation_id": "O003"}],
        "once": True,
    })
    scenario = scenario.model_copy(update={"events": [all_event, any_event]})
    state = SessionState(
        simulation_time=10,
        events=[],
        evidence_by_role={"soc": {"O001"}},
    )
    engine = EventEngine()
    assert [item.id for item in engine.evaluate(scenario, state)] == ["TEST_ALL", "TEST_ANY"]

    fired = EventSnapshot(
        id="runtime-1",
        session_id="session-1",
        sequence=1,
        simulation_time=10,
        event_type=EventType.EVENT_DEFINITION_FIRED,
        payload={"event_definition_id": "TEST_ALL"},
        created_at=datetime.now(UTC),
    )
    state = SessionState(
        simulation_time=10,
        events=[fired],
        evidence_by_role={"soc": {"O001"}},
    )
    assert [item.id for item in engine.evaluate(scenario, state)] == ["TEST_ANY"]


async def test_assessment_trigger_uses_only_ceo_authorized_context_and_fires_once():
    provider = RecordingProvider()
    service = make_service(provider)
    session = await started(service)
    await service.advance_time_async(session.id, 45)
    pressure = next(
        item for item in service.interactions(session.id)
        if item.event_definition_id == "E022"
    )
    assert pressure.started_at == 40

    await service.record_assessment(
        session.id,
        "soc",
        "We assess data exfiltration with medium confidence based on O004.",
    )
    await service.record_assessment(
        session.id,
        "soc",
        "Data exfiltration remains highly likely based on O004.",
    )

    executive = [
        item for item in service.interactions(session.id)
        if item.event_definition_id == "E020"
    ]
    assert len(executive) == 1
    request = next(
        item for item in provider.stakeholder_requests
        if "exfiltration" in item.objective.casefold()
    )
    assert request.role_id == "ceo"
    assert request.permitted_observations == []
    assert request.permitted_findings == []
    serialized = request.model_dump_json()
    assert "FD008" not in serialized
    assert "ground_truth" not in serialized
    assert executive[0].messages[0].message


async def test_dpo_evidence_trigger_receives_only_dpo_knowledge():
    provider = RecordingProvider()
    service = make_service(provider)
    session = await started(service)
    await service.advance_time_async(session.id, 45)

    await service.share_evidence_async(session.id, "soc", "dpo", "O004")
    privacy = next(
        item for item in service.interactions(session.id)
        if item.event_definition_id == "E021"
    )
    assert privacy.actor_role == "dpo"
    request = next(
        item for item in provider.stakeholder_requests
        if "personal data" in item.objective.casefold()
    )
    assert [item.id for item in request.permitted_observations] == ["O004"]
    assert request.permitted_findings == []


async def test_response_snapshot_follow_up_resolution_and_no_scoring_side_effect():
    service = make_service()
    session = await started(service)
    await service.advance_time_async(session.id, 45)
    await service.record_assessment(
        session.id,
        "soc",
        "Data exfiltration is confirmed based on O004.",
    )
    interaction = next(
        item for item in service.interactions(session.id)
        if item.event_definition_id == "E020"
    )
    scenario = service._runtime_scenario(service.get_session(session.id))
    before = service.evaluation_engine.evaluate(scenario, service.repo.events(session.id))

    followed_up = await service.respond_to_interaction(
        session.id,
        interaction.id,
        "Data exfiltration is confirmed.",
    )
    assert followed_up.status == InteractionStatus.WAITING_FOR_TRAINEE
    assert [item.kind for item in followed_up.messages] == ["stakeholder", "follow_up"]

    raw_response = next(
        event for event in service.repo.events(session.id)
        if event.event_type == EventType.TRAINEE_STAKEHOLDER_RESPONSE
    )
    assert raw_response.payload["message"] == "Data exfiltration is confirmed."
    assert raw_response.payload["knowledge_snapshot"] == {
        "stakeholder_role": "ceo",
        "stakeholder_evidence_ids": [],
        "trainee_discovered_evidence_ids": ["O001", "O002", "O003", "O004", "O005"],
    }
    assert raw_response.payload["current_assessments"][0]["hypothesis_id"] == "H002"
    public_response = next(
        event for event in service.events(session.id) if event.id == raw_response.id
    )
    assert public_response.payload == {"redacted": True}

    resolved = await service.respond_to_interaction(
        session.id,
        interaction.id,
        "SOC is collecting the transfer artifacts now.",
    )
    assert resolved.status == InteractionStatus.RESOLVED
    followups = [
        event for event in service.repo.events(session.id)
        if event.event_type == EventType.STAKEHOLDER_FOLLOWUP_CREATED
        and event.payload.get("interaction_id") == interaction.id
    ]
    assert len(followups) == 1

    after = service.evaluation_engine.evaluate(scenario, service.repo.events(session.id))
    assert after == before
