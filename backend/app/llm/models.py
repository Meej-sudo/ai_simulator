from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.scenarios.models import (
    CommunicationStyle,
    FactDefinition,
    PersonalityProfile,
)


class ResponseCertainty(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class RoleResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    role_display_name: str
    responsibilities: list[str]
    communication_style: CommunicationStyle
    personality: PersonalityProfile
    response_guidance: str | None = None
    simulation_time: int
    permitted_facts: list[FactDefinition]
    confidence_semantics: dict[str, str]
    trainee_question: str
    retry_instruction: str | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    referenced_fact_ids: list[str] = Field(default_factory=list)
    certainty: ResponseCertainty


class ValidatedRoleResponse(BaseModel):
    response: RoleResponse
    violations: list[dict[str, object]] = Field(default_factory=list)
