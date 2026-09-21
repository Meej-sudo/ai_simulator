from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.simulation.models import EventType, SessionStatus
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.clock import ClockService
from app.services.scenario_registry import ScenarioRegistry
from app.services.simulation import SimulationService


SCENARIOS = Path(__file__).resolve().parents[2] / "content" / "scenarios"


class AdjustableNow:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, *, seconds: int = 0, minutes: int = 0) -> None:
        self.value += timedelta(seconds=seconds, minutes=minutes)


def make_service(now: AdjustableNow) -> SimulationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    return SimulationService(
        Session(engine),
        registry,
        FakeLLMProvider(),
        clock=ClockService(now),
    )


def started(service: SimulationService):
    session = service.create_session("ransomware_001", "track_alpha", seed=7)
    service.start(session.id)
    return session


def test_clock_service_carries_sub_minute_remainder() -> None:
    now = AdjustableNow()
    clock = ClockService(now)
    last_sync = now()

    now.advance(seconds=20)
    tick = clock.tick(last_sync, 50.0)

    assert tick.elapsed_minutes == 1
    assert tick.remainder_seconds == pytest.approx(10.0)


async def test_clock_sync_preserves_seconds_between_ten_second_polls() -> None:
    now = AdjustableNow()
    service = make_service(now)
    session = started(service)

    now.advance(seconds=10)
    first = await service.sync_clock(session.id)
    assert first.simulation_time == 0
    assert first.clock_remainder_seconds == pytest.approx(10.0)

    now.advance(seconds=10)
    second = await service.sync_clock(session.id)
    assert second.simulation_time == 0
    assert second.clock_remainder_seconds == pytest.approx(20.0)

    now.advance(seconds=40)
    third = await service.sync_clock(session.id)
    assert third.simulation_time == 1
    assert third.clock_remainder_seconds == pytest.approx(0.0)

    advances = [
        event
        for event in service.repo.events(session.id)
        if event.event_type == EventType.TIME_ADVANCED
    ]
    assert len(advances) == 1
    assert advances[0].payload["source"] == "clock"


async def test_pause_resume_and_manual_jump_share_one_clock_state() -> None:
    now = AdjustableNow()
    service = make_service(now)
    session = started(service)

    now.advance(seconds=35)
    paused = await service.pause_clock(session.id)
    assert paused.clock_running is False
    assert paused.clock_remainder_seconds == pytest.approx(35.0)

    now.advance(minutes=5)
    still_paused = await service.sync_clock(session.id)
    assert still_paused.simulation_time == 0
    assert still_paused.clock_remainder_seconds == pytest.approx(35.0)

    resumed = service.resume_clock(session.id)
    assert resumed.clock_running is True
    now.advance(seconds=25)
    advanced = await service.advance_time_async(session.id, 5)

    assert advanced.simulation_time == 6
    assert advanced.clock_remainder_seconds == pytest.approx(0.0)
    sources = [
        event.payload.get("source")
        for event in service.repo.events(session.id)
        if event.event_type == EventType.TIME_ADVANCED
    ]
    assert sources == ["clock", "manual"]


async def test_large_clock_tick_processes_authored_events_at_exact_minutes_once() -> None:
    now = AdjustableNow()
    service = make_service(now)
    session = started(service)

    now.advance(minutes=20)
    synced = await service.sync_clock(session.id)
    assert synced.simulation_time == 20
    assert synced.status == SessionStatus.RUNNING

    triggered = [
        event
        for event in service.repo.events(session.id)
        if event.event_type == EventType.TIMELINE_EVENT_TRIGGERED
    ]
    assert [event.simulation_time for event in triggered] == [5, 10, 20]

    await service.sync_clock(session.id)
    triggered_again = [
        event
        for event in service.repo.events(session.id)
        if event.event_type == EventType.TIMELINE_EVENT_TRIGGERED
    ]
    assert [event.id for event in triggered_again] == [event.id for event in triggered]


async def test_same_minute_events_have_stable_phase_order() -> None:
    now = AdjustableNow()
    service = make_service(now)
    session = started(service)

    now.advance(minutes=35)
    await service.sync_clock(session.id)
    requested = await service.request_investigation(
        session.id,
        "ciso",
        "soc",
        "Determine the login source IP.",
    )
    assert requested.accepted is True
    assert requested.investigation is not None
    assert requested.investigation.due_at == 40

    now.advance(minutes=5)
    await service.sync_clock(session.id)
    at_minute_40 = [
        event
        for event in service.repo.events(session.id)
        if event.simulation_time == 40
    ]
    authored_index = next(
        index
        for index, event in enumerate(at_minute_40)
        if event.event_type == EventType.EVENT_DEFINITION_FIRED
        and event.payload.get("event_definition_id") == "E004"
    )
    investigation_index = next(
        index
        for index, event in enumerate(at_minute_40)
        if event.event_type == EventType.INVESTIGATION_COMPLETED
    )
    assert authored_index < investigation_index
