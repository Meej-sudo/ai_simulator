from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.scenarios.models import Confidence
from app.domain.simulation.models import EventType, SessionStatus
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.errors import InvalidOperationError
from app.services.scenario_registry import ScenarioRegistry
from app.services.simulation import SimulationService


SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def make_service() -> SimulationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    return SimulationService(Session(engine), registry, FakeLLMProvider())


def test_time_knowledge_share_and_evaluation_are_event_driven():
    service = make_service()
    session = service.create_session("ransomware_001", "track_alpha", seed=7)
    service.start(session.id)
    service.advance_time(session.id, 20)

    assert {fact.id for fact in service.role_knowledge(session.id, "soc")} == {
        "F001", "F005"
    }
    assert service.role_knowledge(session.id, "dpo") == []

    service.make_decision(
        session.id,
        "ciso",
        "containment",
        "Isolate the affected servers.",
        None,
        "Limit ongoing encryption.",
    )
    service.advance_time(session.id, 25)
    service.share_fact(session.id, "soc", "dpo", "F003")
    service.complete(session.id)

    assert {fact.id for fact in service.role_knowledge(session.id, "dpo")} == {"F003"}
    result = service.evaluation(session.id)
    scores = {rule.rule_id: rule.awarded_points for rule in result.rules}
    assert scores["involve_dpo"] == 20
    assert scores["share_exfiltration_assessment"] == 20
    assert scores["timely_containment_decision"] == 30


def test_sender_cannot_share_unknown_fact():
    service = make_service()
    session = service.create_session("ransomware_001", "track_bravo", seed=None)
    service.start(session.id)

    try:
        service.share_fact(session.id, "ciso", "dpo", "F003")
    except InvalidOperationError as exc:
        assert "does not know" in str(exc)
    else:
        raise AssertionError("expected InvalidOperationError")


async def test_ask_role_uses_only_current_role_knowledge():
    service = make_service()
    session = service.create_session("ransomware_001", "track_alpha", seed=None)
    service.start(session.id)
    service.advance_time(session.id, 10)

    response = await service.ask_role(session.id, "soc", "What do you know?")

    assert set(response.referenced_fact_ids) == {"F001", "F005"}
    assert "Data exfiltration" not in response.message


def test_complete_is_audited_and_blocks_further_commands():
    service = make_service()
    session = service.create_session("ransomware_001", "track_alpha", seed=None)
    service.start(session.id)
    service.advance_time(session.id, 10)

    completed = service.complete(session.id)

    assert completed.status == SessionStatus.COMPLETED
    assert service.events(session.id)[-1].event_type == EventType.SESSION_COMPLETED
    with pytest.raises(InvalidOperationError, match="must be running"):
        service.advance_time(session.id, 5)
    with pytest.raises(InvalidOperationError, match="must be running"):
        service.make_decision(
            session.id, "ciso", "containment", "A late decision.", None, None
        )


def test_confirmed_exfiltration_conclusion_is_scored_as_premature():
    service = make_service()
    session = service.create_session("ransomware_001", "track_alpha", seed=None)
    service.start(session.id)
    service.advance_time(session.id, 45)
    event = service.make_decision(
        session.id,
        "ciso",
        "exfiltration",
        "We conclude that protected data left the network.",
        Confidence.CONFIRMED,
        "Outbound traffic appears suspicious.",
    )
    service.complete(session.id)

    assert event.payload["decision_category"] == "exfiltration"
    assert event.payload["confidence"] == "confirmed"
    result = service.evaluation(session.id)
    rule = next(
        item
        for item in result.rules
        if item.rule_id == "avoid_premature_exfiltration_claim"
    )
    assert rule.awarded_points == 0


def test_decision_category_must_be_defined_by_scenario():
    service = make_service()
    session = service.create_session("ransomware_001", "track_alpha", seed=None)
    service.start(session.id)

    with pytest.raises(InvalidOperationError, match="not available"):
        service.make_decision(
            session.id, "ciso", "hidden_answer", "Do something.", None, None
        )
