from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.scenarios.models import CommunicationStyle, Confidence
from app.domain.simulation.models import EventType, SessionStatus
from app.llm.models import ResponseCertainty


class CreateSessionRequest(BaseModel):
    scenario_id: str
    variant_id: str
    seed: int | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_id: str
    variant_id: str
    seed: int | None
    simulation_time: int
    status: SessionStatus
    created_at: datetime


class AdvanceTimeRequest(BaseModel):
    minutes: int = Field(gt=0)


class AskRoleRequest(BaseModel):
    target_role: str
    message: str = Field(min_length=1, max_length=4000)


class AskRoleResponse(BaseModel):
    message: str
    referenced_fact_ids: list[str]
    certainty: ResponseCertainty


class ShareFactRequest(BaseModel):
    from_role: str
    to_role: str
    fact_id: str


class DecisionRequest(BaseModel):
    actor_role: str
    category: str
    decision: str = Field(min_length=1, max_length=4000)
    confidence: Confidence | None = None
    rationale: str | None = Field(default=None, max_length=4000)


class ActionAcceptedResponse(BaseModel):
    event_id: str
    simulation_time: int


class FactResponse(BaseModel):
    id: str
    type: str
    statement: str
    confidence: Confidence


class KnowledgeResponse(BaseModel):
    role_id: str
    simulation_time: int
    facts: list[FactResponse]


class RoleResponse(BaseModel):
    id: str
    display_name: str
    responsibilities: list[str]
    communication_style: CommunicationStyle


class VariantResponse(BaseModel):
    id: str
    name: str


class DecisionCategoryResponse(BaseModel):
    id: str
    display_name: str
    description: str
    captures_confidence: bool


class ScenarioSummaryResponse(BaseModel):
    id: str
    name: str
    description: str
    duration_minutes: int
    variants: list[VariantResponse]
    decision_categories: list[DecisionCategoryResponse]


class ScenarioDetailResponse(ScenarioSummaryResponse):
    roles: list[RoleResponse]


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    sequence: int
    simulation_time: int
    event_type: EventType
    actor_role: str | None
    target_role: str | None
    payload: dict[str, Any]
    created_at: datetime
