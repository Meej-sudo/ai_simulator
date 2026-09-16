from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.scenarios.models import Confidence
from app.domain.simulation.models import EventType, InvestigationStatus, SessionStatus
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.errors import InvalidOperationError
from app.services.scenario_registry import ScenarioRegistry
from app.services.simulation import SimulationService


SCENARIOS = Path(__file__).resolve().parents[2] / "content" / "scenarios"


def make_service() -> SimulationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    return SimulationService(Session(engine), registry, FakeLLMProvider())


def started(service: SimulationService, variant: str = "track_alpha"):
    session = service.create_session("ransomware_001", variant, seed=7)
    service.start(session.id)
    return session


def test_timeline_reveals_only_observations_to_the_target_role():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 20)

    soc = service.role_knowledge(session.id, "soc")
    ciso = service.role_knowledge(session.id, "ciso")

    assert {item.id for item in soc.observations} == {"O001", "O002", "O003"}
    assert soc.findings == []
    assert ciso.evidence_ids == set()


async def test_investigation_completes_at_exact_boundary_once():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 45)

    requested = await service.request_investigation(
        session.id,
        "ciso",
        "soc",
        "Find where that outbound traffic went.",
    )
    assert requested.accepted is True
    assert requested.investigation.due_at == 50

    service.advance_time(session.id, 4)
    assert "FD004" not in service.role_knowledge(session.id, "soc").evidence_ids
    assert service.investigations(session.id)[0].status == InvestigationStatus.IN_PROGRESS

    service.advance_time(session.id, 1)
    assert "FD004" in service.role_knowledge(session.id, "soc").evidence_ids
    assert service.investigations(session.id)[0].completed_at == 50

    service.advance_time(session.id, 5)
    completions = [
        event for event in service.repo.events(session.id)
        if event.event_type == EventType.INVESTIGATION_COMPLETED
    ]
    reveals = [
        event for event in service.repo.events(session.id)
        if event.event_type == EventType.FINDING_REVEALED
    ]
    assert len(completions) == 1
    assert len(reveals) == 1


async def test_findings_are_role_isolated_until_explicitly_shared():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 45)
    await service.request_investigation(
        session.id, "ciso", "soc", "Identify the outbound destination."
    )
    service.advance_time(session.id, 5)

    assert "FD004" in service.role_knowledge(session.id, "soc").evidence_ids
    assert "FD004" not in service.role_knowledge(session.id, "dpo").evidence_ids

    service.share_evidence(session.id, "soc", "dpo", "FD004")

    assert "FD004" in service.role_knowledge(session.id, "dpo").evidence_ids


async def test_variant_outcomes_diverge_behind_same_public_request():
    alpha = make_service()
    bravo = make_service()
    alpha_session = started(alpha, "track_alpha")
    bravo_session = started(bravo, "track_bravo")
    alpha.advance_time(alpha_session.id, 45)
    bravo.advance_time(bravo_session.id, 45)

    await alpha.request_investigation(
        alpha_session.id, "ciso", "soc", "Where did the outbound traffic go?"
    )
    await bravo.request_investigation(
        bravo_session.id, "ciso", "soc", "Where did the outbound traffic go?"
    )
    alpha.advance_time(alpha_session.id, 5)
    bravo.advance_time(bravo_session.id, 5)

    assert "FD004" in alpha.role_knowledge(alpha_session.id, "soc").evidence_ids
    assert "FD010" in bravo.role_knowledge(bravo_session.id, "soc").evidence_ids


async def test_prerequisites_and_nonrepeatability_are_enforced_before_llm_routing():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 10)

    unavailable = await service.request_investigation(
        session.id, "ciso", "soc", "Find the outbound destination."
    )
    assert unavailable.accepted is False
    assert service.investigations(session.id) == []

    service.advance_time(session.id, 35)
    accepted = await service.request_investigation(
        session.id, "ciso", "soc", "Find the outbound destination."
    )
    assert accepted.accepted is True
    service.advance_time(session.id, 5)
    duplicate = await service.request_investigation(
        session.id, "ciso", "soc", "Find the outbound destination."
    )
    assert duplicate.accepted is False
    assert len(service.investigations(session.id)) == 1


async def test_unmatched_free_text_is_audited_without_revealing_a_finding():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 45)

    result = await service.request_investigation(
        session.id, "ciso", "soc", "Order lunch for the response team."
    )

    assert result.accepted is False
    event_types = [event.event_type for event in service.repo.events(session.id)]
    assert EventType.INVESTIGATION_MATCH_FAILED in event_types
    assert EventType.INVESTIGATION_STARTED not in event_types
    assert EventType.FINDING_REVEALED not in event_types


async def test_role_chat_uses_only_current_role_evidence():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 10)

    response = await service.ask_role(session.id, "soc", "What do you know?")

    assert set(response.referenced_evidence_ids) == {"O001", "O002"}
    assert "outbound" not in response.message.casefold()
    assert "FD" not in response.message


async def test_assessments_append_history_and_project_latest_without_grading():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 45)

    first = await service.record_assessment(
        session.id,
        "soc",
        "Data exfiltration is plausible with medium confidence based on O004.",
    )
    second = await service.record_assessment(
        session.id,
        "soc",
        "Data exfiltration is now confirmed based on O004.",
    )
    projection = service.assessments(session.id)

    assert first[0].confidence == Confidence.MEDIUM
    assert second[0].confidence == Confidence.CONFIRMED
    assert second[0].basis_evidence_ids == ["O004"]
    assert len(projection.history) == 2
    assert len(projection.current) == 1
    assert projection.current[0].confidence == Confidence.CONFIRMED
    serialized = projection.model_dump_json().casefold()
    assert "correct" not in serialized
    assert "ground_truth" not in serialized


async def test_assessment_cannot_cite_evidence_unknown_to_actor():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 45)

    recorded = await service.record_assessment(
        session.id,
        "dpo",
        "Data exfiltration is plausible based on FD008.",
    )

    assert recorded[0].basis_evidence_ids == []


async def test_scoring_uses_evidence_sharing_decisions_and_assessment_events():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 20)
    service.make_decision(
        session.id,
        "ciso",
        "containment",
        "Isolate affected servers.",
        None,
        "Limit ongoing encryption.",
    )
    service.advance_time(session.id, 25)
    service.share_evidence(session.id, "soc", "dpo", "O004")
    await service.record_assessment(
        session.id,
        "ciso",
        "Data exfiltration is confirmed.",
    )
    service.complete(session.id)

    scores = {
        rule.rule_id: rule.awarded_points
        for rule in service.evaluation(session.id).rules
    }
    assert scores["involve_dpo"] == 20
    assert scores["share_outbound_observation"] == 20
    assert scores["timely_containment_decision"] == 30
    assert scores["avoid_premature_exfiltration_claim"] == 0


def test_sender_cannot_share_unknown_evidence():
    service = make_service()
    session = started(service)

    with pytest.raises(InvalidOperationError, match="does not know"):
        service.share_evidence(session.id, "ciso", "dpo", "O004")


def test_complete_is_audited_and_blocks_further_commands():
    service = make_service()
    session = started(service)
    service.advance_time(session.id, 10)

    completed = service.complete(session.id)

    assert completed.status == SessionStatus.COMPLETED
    assert service.events(session.id)[-1].event_type == EventType.SESSION_COMPLETED
    with pytest.raises(InvalidOperationError, match="must be running"):
        service.advance_time(session.id, 5)


def test_decision_category_must_be_defined_by_scenario():
    service = make_service()
    session = started(service)

    with pytest.raises(InvalidOperationError, match="not available"):
        service.make_decision(
            session.id, "ciso", "hidden_answer", "Do something.", None, None
        )


def test_session_is_pinned_to_immutable_variant_snapshot():
    service = make_service()
    session = started(service)
    original_name = service._runtime_scenario(session).scenario.name
    original_version = session.scenario_version

    service.scenarios.get("ransomware_001").scenario.name = "Edited after start"

    restored = service._runtime_scenario(session)
    assert restored.scenario.name == original_name
    assert session.scenario_version == original_version
    assert len(original_version) == 64
    assert "variants" not in session.scenario_snapshot
    assert session.scenario_snapshot["variant_id"] == "track_alpha"
    assert "investigation_outcomes" in session.scenario_snapshot
