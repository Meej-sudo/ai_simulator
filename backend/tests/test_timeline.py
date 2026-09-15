import pytest

from app.domain.scenarios.models import TimelineEvent
from app.domain.simulation.timeline import TimelineEngine


def event(identifier: str, minute: int) -> TimelineEvent:
    return TimelineEvent(
        id=identifier,
        at_minute=minute,
        type="observation_grant",
        role="soc",
        observation_ids=["O001"],
    )


def test_due_events_use_open_closed_time_interval():
    events = [
        event("before", 19),
        event("lower", 20),
        event("inside", 25),
        event("upper", 35),
        event("after", 36),
    ]

    due = TimelineEngine.due_events(events, current_time=20, new_time=35)

    assert [item.id for item in due] == ["inside", "upper"]


def test_time_cannot_move_backwards():
    with pytest.raises(ValueError, match="backwards"):
        TimelineEngine.due_events([], current_time=20, new_time=19)
