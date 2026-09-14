from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"


class EventType(StrEnum):
    SESSION_STARTED = "SESSION_STARTED"
    TIME_ADVANCED = "TIME_ADVANCED"
    TIMELINE_EVENT_TRIGGERED = "TIMELINE_EVENT_TRIGGERED"
    FACT_LEARNED = "FACT_LEARNED"
    QUESTION_ASKED = "QUESTION_ASKED"
    ROLE_RESPONDED = "ROLE_RESPONDED"
    FACT_SHARED = "FACT_SHARED"
    DECISION_MADE = "DECISION_MADE"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    LLM_POLICY_VIOLATION = "LLM_POLICY_VIOLATION"


class EventSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    sequence: int
    simulation_time: int
    event_type: EventType
    actor_role: str | None = None
    target_role: str | None = None
    payload: dict[str, Any]
    created_at: datetime
