from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"


class Reliability(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"


CONFIDENCE_SEMANTICS: dict[Confidence, str] = {
    Confidence.LOW: "weak indication or preliminary belief",
    Confidence.MEDIUM: "suspected or plausible, but unconfirmed",
    Confidence.HIGH: "supported by strong evidence and highly likely",
    Confidence.CONFIRMED: "stated as established or certain",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ScenarioIdentifier = Annotated[
    str,
    Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$"),
]
EvidenceIdentifier = Annotated[
    str,
    Field(min_length=1, pattern=r"^(?:O|FD)[0-9]+$"),
]


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


class PersonalityTraits(StrictModel):
    openness: Literal["low", "medium", "high"]
    conscientiousness: Literal["low", "medium", "high"]
    extraversion: Literal["low", "medium", "high"]
    agreeableness: Literal["low", "medium", "high"]
    emotional_stability: Literal["low", "medium", "high"]


class PersonalityProfile(StrictModel):
    summary: str = Field(min_length=1, max_length=500)
    traits: PersonalityTraits
    behavioral_tendencies: list[str] = Field(min_length=1, max_length=6)
    under_pressure: str = Field(min_length=1, max_length=500)


class RoleDefinition(StrictModel):
    id: str
    display_name: str
    responsibilities: list[str] = Field(min_length=1)
    communication_style: CommunicationStyle
    personality: PersonalityProfile
    response_guidance: str | None = None


class ExternalEntityDefinition(StrictModel):
    id: ScenarioIdentifier
    display_name: str = Field(min_length=1)
    type: ScenarioIdentifier
    accepts: list[ScenarioIdentifier] = Field(min_length=1)


class ObservationDefinition(StrictModel):
    id: EvidenceIdentifier
    source: ScenarioIdentifier
    statement: str = Field(min_length=1)
    reliability: Reliability


class FindingDefinition(StrictModel):
    id: EvidenceIdentifier
    statement: str = Field(min_length=1)
    reliability: Reliability


EvidenceDefinition = ObservationDefinition | FindingDefinition


class HypothesisDefinition(StrictModel):
    id: str = Field(min_length=1, pattern=r"^H[0-9]+$")
    key: ScenarioIdentifier
    label: str = Field(min_length=1)


class InvestigationPrerequisites(StrictModel):
    all_evidence: list[EvidenceIdentifier] = Field(default_factory=list)
    any_evidence: list[EvidenceIdentifier] = Field(default_factory=list)


class InvestigationDefinition(StrictModel):
    id: str = Field(min_length=1, pattern=r"^I[0-9]+$")
    label: str = Field(min_length=1)
    performer_roles: list[str] = Field(min_length=1)
    request_description: str = Field(min_length=1)
    match_hints: list[str] = Field(min_length=1)
    prerequisites: InvestigationPrerequisites = Field(
        default_factory=InvestigationPrerequisites
    )
    duration_minutes: int = Field(ge=0)
    repeatable: bool = False


class TimelineEvent(StrictModel):
    id: str
    at_minute: int = Field(ge=0)
    type: Literal["observation_grant"]
    role: str
    observation_ids: list[EvidenceIdentifier] = Field(min_length=1)


class ObservationOverride(StrictModel):
    observation_id: EvidenceIdentifier
    statement: str | None = None
    reliability: Reliability | None = None


class TimelineOverride(StrictModel):
    event_id: str
    at_minute: int | None = Field(default=None, ge=0)
    role: str | None = None
    observation_ids: list[EvidenceIdentifier] | None = None
    enabled: bool = True


class InvestigationOutcome(StrictModel):
    investigation_id: str
    reveal_findings: list[EvidenceIdentifier] = Field(min_length=1)


class VariantDefinition(StrictModel):
    id: str
    name: str
    ground_truth: dict[str, Any]
    observation_overrides: list[ObservationOverride] = Field(default_factory=list)
    timeline_overrides: list[TimelineOverride] = Field(default_factory=list)
    investigation_outcomes: list[InvestigationOutcome] = Field(min_length=1)


class ScoringRule(StrictModel):
    id: str
    description: str
    type: Literal[
        "role_contacted_within",
        "evidence_shared_within",
        "decision_within",
        "avoid_premature_assessment",
    ]
    points: int = Field(gt=0)
    within_minutes: int | None = Field(default=None, gt=0)
    trigger_evidence: EvidenceIdentifier | None = None
    target_role: str | None = None
    evidence_id: EvidenceIdentifier | None = None
    decision_category: str | None = None
    hypothesis_id: str | None = None
    conclusion_confidence: Confidence | None = None
    confirmation_evidence: EvidenceIdentifier | None = None

    @model_validator(mode="after")
    def validate_fields_for_type(self) -> "ScoringRule":
        required: dict[str, tuple[str, ...]] = {
            "role_contacted_within": (
                "trigger_evidence",
                "target_role",
                "within_minutes",
            ),
            "evidence_shared_within": (
                "trigger_evidence",
                "target_role",
                "evidence_id",
                "within_minutes",
            ),
            "decision_within": (
                "trigger_evidence",
                "decision_category",
                "within_minutes",
            ),
            "avoid_premature_assessment": (
                "hypothesis_id",
                "conclusion_confidence",
                "confirmation_evidence",
            ),
        }
        missing = [name for name in required[self.type] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.type} requires: {', '.join(missing)}")
        return self


class CompiledScenario(StrictModel):
    scenario: ScenarioMetadata
    roles: list[RoleDefinition]
    external_entities: list[ExternalEntityDefinition]
    observations: list[ObservationDefinition]
    findings: list[FindingDefinition]
    hypotheses: list[HypothesisDefinition]
    investigations: list[InvestigationDefinition]
    timeline: list[TimelineEvent]
    variants: list[VariantDefinition]
    scoring_rules: list[ScoringRule]

    def role(self, role_id: str) -> RoleDefinition:
        return next(role for role in self.roles if role.id == role_id)

    def observation(self, observation_id: str) -> ObservationDefinition:
        return next(item for item in self.observations if item.id == observation_id)

    def finding(self, finding_id: str) -> FindingDefinition:
        return next(item for item in self.findings if item.id == finding_id)

    def evidence(self, evidence_id: str) -> EvidenceDefinition:
        for item in [*self.observations, *self.findings]:
            if item.id == evidence_id:
                return item
        raise StopIteration

    def hypothesis(self, hypothesis_id: str) -> HypothesisDefinition:
        return next(item for item in self.hypotheses if item.id == hypothesis_id)

    def investigation(self, investigation_id: str) -> InvestigationDefinition:
        return next(item for item in self.investigations if item.id == investigation_id)

    def external_entity(self, entity_id: str) -> ExternalEntityDefinition:
        return next(
            entity for entity in self.external_entities if entity.id == entity_id
        )

    def variant(self, variant_id: str) -> VariantDefinition:
        return next(variant for variant in self.variants if variant.id == variant_id)


class RuntimeScenario(StrictModel):
    """Variant-resolved scenario with hidden truth and outcomes excluded from dumps."""

    scenario: ScenarioMetadata
    roles: list[RoleDefinition]
    external_entities: list[ExternalEntityDefinition]
    observations: list[ObservationDefinition]
    findings: list[FindingDefinition]
    hypotheses: list[HypothesisDefinition]
    investigations: list[InvestigationDefinition]
    timeline: list[TimelineEvent]
    scoring_rules: list[ScoringRule]
    variant_id: str
    ground_truth: dict[str, Any] = Field(exclude=True)
    investigation_outcomes: list[InvestigationOutcome] = Field(exclude=True)

    def role(self, role_id: str) -> RoleDefinition:
        return next(role for role in self.roles if role.id == role_id)

    def observation(self, observation_id: str) -> ObservationDefinition:
        return next(item for item in self.observations if item.id == observation_id)

    def finding(self, finding_id: str) -> FindingDefinition:
        return next(item for item in self.findings if item.id == finding_id)

    def evidence(self, evidence_id: str) -> EvidenceDefinition:
        for item in [*self.observations, *self.findings]:
            if item.id == evidence_id:
                return item
        raise StopIteration

    def hypothesis(self, hypothesis_id: str) -> HypothesisDefinition:
        return next(item for item in self.hypotheses if item.id == hypothesis_id)

    def investigation(self, investigation_id: str) -> InvestigationDefinition:
        return next(item for item in self.investigations if item.id == investigation_id)

    def investigation_outcome(self, investigation_id: str) -> InvestigationOutcome:
        return next(
            item
            for item in self.investigation_outcomes
            if item.investigation_id == investigation_id
        )

    def external_entity(self, entity_id: str) -> ExternalEntityDefinition:
        return next(
            entity for entity in self.external_entities if entity.id == entity_id
        )
