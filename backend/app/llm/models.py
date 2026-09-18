from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.scenarios.models import (
    CommunicationStyle,
    Confidence,
    FindingDefinition,
    HypothesisDefinition,
    ObservationDefinition,
    PersonalityProfile,
)


class ResponseCertainty(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class ThreadTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["trainee", "role"]
    text: str
    simulation_time: int


class RoleResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    role_display_name: str
    responsibilities: list[str]
    communication_style: CommunicationStyle
    personality: PersonalityProfile
    response_guidance: str | None = None
    simulation_time: int
    permitted_observations: list[ObservationDefinition]
    permitted_findings: list[FindingDefinition]
    thread_history: list[ThreadTurn] = Field(default_factory=list)
    trainee_question: str
    retry_instruction: str | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    referenced_evidence_ids: list[str] = Field(default_factory=list)
    certainty: ResponseCertainty


class ValidatedRoleResponse(BaseModel):
    response: RoleResponse
    violations: list[dict[str, object]] = Field(default_factory=list)


class EligibleInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    request_description: str
    match_hints: list[str]


class InvestigationInterpretationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trainee_request: str = Field(min_length=1)
    performer_role: str
    eligible_investigations: list[EligibleInvestigation]
    retry_instruction: str | None = None


class InvestigationInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    investigation_id: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def validate_match(self) -> "InvestigationInterpretation":
        if self.matched != (self.investigation_id is not None):
            raise ValueError("matched must be true exactly when investigation_id is present")
        return self


class ValidatedInvestigationInterpretation(BaseModel):
    response: InvestigationInterpretation
    violations: list[dict[str, object]] = Field(default_factory=list)


class AssessmentInterpretationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trainee_statement: str = Field(min_length=1)
    actor_role: str
    hypotheses: list[HypothesisDefinition]
    known_observations: list[ObservationDefinition]
    known_findings: list[FindingDefinition]
    confidence_semantics: dict[str, str]
    retry_instruction: str | None = None


class NormalizedAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    confidence: Confidence
    basis_evidence_ids: list[str] = Field(default_factory=list)


class AssessmentInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[NormalizedAssessment] = Field(default_factory=list)


class ValidatedAssessmentInterpretation(BaseModel):
    response: AssessmentInterpretation
    violations: list[dict[str, object]] = Field(default_factory=list)


class StakeholderAssessmentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    hypothesis_label: str
    confidence: Confidence
    statement: str


class StakeholderMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    role_display_name: str
    responsibilities: list[str]
    communication_style: CommunicationStyle
    personality: PersonalityProfile
    response_guidance: str | None = None
    objective: str = Field(min_length=1)
    context: list[str] = Field(default_factory=list)
    permitted_observations: list[ObservationDefinition]
    permitted_findings: list[FindingDefinition]
    relevant_assessments: list[StakeholderAssessmentContext] = Field(default_factory=list)


class StakeholderMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
