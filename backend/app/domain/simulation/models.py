from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.scenarios.models import Confidence


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
    OBSERVATION_REVEALED = "OBSERVATION_REVEALED"
    INVESTIGATION_REQUESTED = "INVESTIGATION_REQUESTED"
    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_MATCH_FAILED = "INVESTIGATION_MATCH_FAILED"
    INVESTIGATION_REJECTED = "INVESTIGATION_REJECTED"
    FINDING_REVEALED = "FINDING_REVEALED"
    EVIDENCE_SHARED = "EVIDENCE_SHARED"
    ASSESSMENT_RECORDED = "ASSESSMENT_RECORDED"
    ASSESSMENT_INTERPRETATION_FAILED = "ASSESSMENT_INTERPRETATION_FAILED"


class InvestigationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


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

class InvestigationRun(BaseModel):
    id: str
    investigation_id: str
    label: str
    requester_role: str
    performer_role: str
    request: str
    status: InvestigationStatus
    started_at: int
    due_at: int
    completed_at: int | None = None


class AssessmentSnapshot(BaseModel):
    event_id: str
    hypothesis_id: str
    hypothesis_key: str
    hypothesis_label: str
    actor_role: str
    confidence: Confidence
    basis_evidence_ids: list[str]
    statement: str
    recorded_at: int


class InvestigationRequestResult(BaseModel):
    accepted: bool
    reason: str
    investigation: InvestigationRun | None = None


class AssessmentProjection(BaseModel):
    history: list[AssessmentSnapshot]
    current: list[AssessmentSnapshot]
