from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.simulation.models import EventType
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.errors import InvalidOperationError
from app.services.scenario_registry import ScenarioRegistry
from app.services.simulation import SimulationService


SCENARIOS = Path(__file__).resolve().parents[2] / "content" / "scenarios"


class RecordingProvider(FakeLLMProvider):
    def __init__(self):
        self.role_requests = []

    async def generate_role_response(self, request):
        self.role_requests.append(request)
        return await super().generate_role_response(request)


def make_service(provider=None) -> SimulationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    return SimulationService(
        Session(engine),
        registry,
        provider or FakeLLMProvider(),
    )


def started(service: SimulationService):
    session = service.create_session("ransomware_001", "track_alpha", seed=7)
    service.start(session.id)
    service.advance_time(session.id, 10)
    return session


def test_external_trainee_bridge_citation_shares_discovered_evidence_to_every_role():
    service = make_service()
    session = started(service)

    posted = service.post_message(
        session.id,
        "channel:bridge",
        "Use this observation in the response.",
        ["O001"],
    )

    assert posted.event_type == EventType.MESSAGE_POSTED
    assert posted.actor_role is None
    assert posted.payload["sender"] == "trainee"
    for role in service.roles(session.id):
        assert "O001" in service.role_knowledge(session.id, role.id).evidence_ids


def test_external_trainee_dm_citation_shares_only_with_addressed_role():
    service = make_service()
    session = started(service)

    service.post_message(session.id, "dm:dpo", "Please review this.", ["O002"])

    assert "O002" in service.role_knowledge(session.id, "dpo").evidence_ids
    assert "O002" not in service.role_knowledge(session.id, "ciso").evidence_ids


def test_external_trainee_cannot_cite_undiscovered_evidence():
    service = make_service()
    session = started(service)

    with pytest.raises(InvalidOperationError, match="has not been discovered"):
        service.post_message(session.id, "channel:bridge", "Review this.", ["FD004"])


async def test_role_conversation_history_is_scoped_ordered_and_capped():
    provider = RecordingProvider()
    service = make_service(provider)
    session = started(service)

    await service.ask_role(session.id, "soc", "SOC question one")
    await service.ask_role(session.id, "ciso", "CISO private question")
    await service.ask_role(session.id, "soc", "SOC question two")
    await service.ask_role(session.id, "soc", "SOC question three")
    await service.ask_role(session.id, "soc", "SOC question four")

    history = provider.role_requests[-1].thread_history
    assert len(history) == 6
    assert [turn.speaker for turn in history] == [
        "trainee",
        "role",
        "trainee",
        "role",
        "trainee",
        "role",
    ]
    assert history[0].text == "SOC question one"
    assert history[-2].text == "SOC question three"
    assert all("CISO private question" not in turn.text for turn in history)
