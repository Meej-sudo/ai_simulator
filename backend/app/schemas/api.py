from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.scenarios.models import (
    CommunicationStyle,
    CompiledScenario,
    Confidence,
    Reliability,
)
from app.domain.simulation.models import (
    AssessmentProjection,
    AssessmentSnapshot,
    EventType,
    InvestigationRun,
    SessionStatus,
)
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
    referenced_evidence_ids: list[str]
    certainty: ResponseCertainty


class ShareEvidenceRequest(BaseModel):
    from_role: str
    to_role: str
    evidence_id: str


class ShareFactRequest(BaseModel):
    from_role: str
    to_role: str
    fact_id: str


class InvestigationRequest(BaseModel):
    requester_role: str
    performer_role: str
    request: str = Field(min_length=1, max_length=4000)


class InvestigationRequestResponse(BaseModel):
    accepted: bool
    reason: str
    investigation: InvestigationRun | None = None


class AssessmentRequest(BaseModel):
    actor_role: str
    statement: str = Field(min_length=1, max_length=4000)


class AssessmentSubmissionResponse(BaseModel):
    recorded: list[AssessmentSnapshot]
    message: str


class DecisionRequest(BaseModel):
    actor_role: str
    category: str
    decision: str = Field(min_length=1, max_length=4000)
    confidence: Confidence | None = None
    rationale: str | None = Field(default=None, max_length=4000)


class ActionAcceptedResponse(BaseModel):
    event_id: str
    simulation_time: int


class ObservationResponse(BaseModel):
    id: str
    source: str
    statement: str
    reliability: Reliability


class FindingResponse(BaseModel):
    id: str
    statement: str
    reliability: Reliability


class KnowledgeResponse(BaseModel):
    role_id: str
    simulation_time: int
    observations: list[ObservationResponse]
    findings: list[FindingResponse]


class RoleResponse(BaseModel):
    id: str
    display_name: str
    responsibilities: list[str]
    communication_style: CommunicationStyle


class ExternalEntityResponse(BaseModel):
    id: str
    display_name: str
    type: str
    accepts: list[str]


class HypothesisResponse(BaseModel):
    id: str
    key: str
    label: str


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
    external_entities: list[ExternalEntityResponse]
    hypotheses: list[HypothesisResponse]


class ScenarioSourcesUpdateRequest(BaseModel):
    files: dict[str, str] = Field(min_length=9, max_length=9)

    @field_validator("files")
    @classmethod
    def reject_oversized_request(cls, files: dict[str, str]) -> dict[str, str]:
        if sum(len(content.encode("utf-8")) for content in files.values()) > 2_000_000:
            raise ValueError("scenario source payload exceeds the 2000000-byte limit")
        return files


class ScenarioSourcesResponse(BaseModel):
    scenario: ScenarioSummaryResponse
    files: dict[str, str]


class ScenarioAuthoringUpdateRequest(BaseModel):
    document: CompiledScenario


class ScenarioAuthoringResponse(BaseModel):
    scenario: ScenarioSummaryResponse
    document: CompiledScenario


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
