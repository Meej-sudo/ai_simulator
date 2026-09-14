from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"


CONFIDENCE_SEMANTICS: dict[Confidence, str] = {
    Confidence.LOW: "weak indication or preliminary signal",
    Confidence.MEDIUM: "suspected or plausible, but unconfirmed",
    Confidence.HIGH: "supported by strong evidence and highly likely",
    Confidence.CONFIRMED: "established as a confirmed fact",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionCategoryDefinition(StrictModel):
    id: str
    display_name: str
    description: str = ""
    captures_confidence: bool = False


class ScenarioMetadata(StrictModel):
    id: str
    name: str
    description: str = ""
    duration_minutes: int = Field(gt=0)
    decision_categories: list[DecisionCategoryDefinition] = Field(min_length=1)

    def decision_category(self, category_id: str) -> DecisionCategoryDefinition:
        return next(item for item in self.decision_categories if item.id == category_id)


class CommunicationStyle(StrictModel):
    tone: str
    verbosity: Literal["low", "medium", "high"] = "medium"


class RoleDefinition(StrictModel):
    id: str
    display_name: str
    responsibilities: list[str] = Field(min_length=1)
    communication_style: CommunicationStyle
    response_guidance: str | None = None


class FactDefinition(StrictModel):
    id: str
    type: Literal["observation", "assessment"]
    statement: str
    confidence: Confidence = Confidence.CONFIRMED


class TimelineEvent(StrictModel):
    id: str
    at_minute: int = Field(ge=0)
    type: Literal["knowledge_grant"]
    role: str
    fact_ids: list[str] = Field(min_length=1)


class FactOverride(StrictModel):
    fact_id: str
    statement: str | None = None
    confidence: Confidence | None = None


class TimelineOverride(StrictModel):
    event_id: str
    at_minute: int | None = Field(default=None, ge=0)
    role: str | None = None
    fact_ids: list[str] | None = None
    enabled: bool = True


class VariantDefinition(StrictModel):
    id: str
    name: str
    ground_truth: dict[str, Any]
    fact_overrides: list[FactOverride] = Field(default_factory=list)
    timeline_overrides: list[TimelineOverride] = Field(default_factory=list)


class ScoringRule(StrictModel):
    id: str
    description: str
    type: Literal[
        "role_contacted_within",
        "fact_shared_within",
        "decision_within",
        "avoid_premature_conclusion",
    ]
    points: int = Field(gt=0)
    within_minutes: int | None = Field(default=None, gt=0)
    trigger_fact: str | None = None
    target_role: str | None = None
    fact_id: str | None = None
    decision_category: str | None = None
    conclusion_confidence: Confidence | None = None
    confirmation_fact: str | None = None

    @model_validator(mode="after")
    def validate_fields_for_type(self) -> "ScoringRule":
        required: dict[str, tuple[str, ...]] = {
            "role_contacted_within": ("trigger_fact", "target_role", "within_minutes"),
            "fact_shared_within": ("trigger_fact", "target_role", "fact_id", "within_minutes"),
            "decision_within": (
                "trigger_fact",
                "decision_category",
                "within_minutes",
            ),
            "avoid_premature_conclusion": (
                "decision_category",
                "conclusion_confidence",
                "confirmation_fact",
            ),
        }
        missing = [name for name in required[self.type] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.type} requires: {', '.join(missing)}")
        return self


class CompiledScenario(StrictModel):
    scenario: ScenarioMetadata
    roles: list[RoleDefinition]
    facts: list[FactDefinition]
    timeline: list[TimelineEvent]
    variants: list[VariantDefinition]
    scoring_rules: list[ScoringRule]

    def role(self, role_id: str) -> RoleDefinition:
        return next(role for role in self.roles if role.id == role_id)

    def fact(self, fact_id: str) -> FactDefinition:
        return next(fact for fact in self.facts if fact.id == fact_id)

    def variant(self, variant_id: str) -> VariantDefinition:
        return next(variant for variant in self.variants if variant.id == variant_id)


class RuntimeScenario(StrictModel):
    """Variant-resolved scenario. ground_truth deliberately remains separate."""

    scenario: ScenarioMetadata
    roles: list[RoleDefinition]
    facts: list[FactDefinition]
    timeline: list[TimelineEvent]
    scoring_rules: list[ScoringRule]
    variant_id: str
    ground_truth: dict[str, Any] = Field(exclude=True)

    def role(self, role_id: str) -> RoleDefinition:
        return next(role for role in self.roles if role.id == role_id)

    def fact(self, fact_id: str) -> FactDefinition:
        return next(fact for fact in self.facts if fact.id == fact_id)
