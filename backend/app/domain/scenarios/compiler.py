from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import (
    CompiledScenario,
    ExternalEntityDefinition,
    FindingDefinition,
    HypothesisDefinition,
    InvestigationDefinition,
    ObservationDefinition,
    RoleDefinition,
    RuntimeScenario,
    ScenarioMetadata,
    ScoringRule,
    TimelineEvent,
    VariantDefinition,
)


class ScenarioValidationError(ValueError):
    pass


class ScenarioCompiler:
    REQUIRED_FILES = (
        "scenario.yaml",
        "roles.yaml",
        "external_entities.yaml",
        "evidence.yaml",
        "hypotheses.yaml",
        "investigations.yaml",
        "timeline.yaml",
        "variants.yaml",
        "scoring.yaml",
    )

    def compile(self, directory: str | Path) -> CompiledScenario:
        path = Path(directory)
        missing = [name for name in self.REQUIRED_FILES if not (path / name).is_file()]
        if missing:
            raise ScenarioValidationError(f"missing scenario files: {', '.join(missing)}")

        try:
            metadata = ScenarioMetadata.model_validate(
                self._load(path / "scenario.yaml")["scenario"]
            )
            raw_roles = self._list(self._load(path / "roles.yaml"), "roles")
            raw_external_entities = self._list(
                self._load(path / "external_entities.yaml"), "external_entities"
            )
            evidence = self._load(path / "evidence.yaml")
            raw_observations = self._list(evidence, "observations")
            raw_findings = self._list(evidence, "findings")
            raw_hypotheses = self._list(
                self._load(path / "hypotheses.yaml"), "hypotheses"
            )
            raw_investigations = self._list(
                self._load(path / "investigations.yaml"), "investigations"
            )
            raw_timeline = self._list(self._load(path / "timeline.yaml"), "events")
            raw_variants = self._list(self._load(path / "variants.yaml"), "variants")
            raw_rules = self._list(self._load(path / "scoring.yaml"), "rules")
            self._ensure_unique("role", raw_roles)
            self._ensure_unique("external entity", raw_external_entities)
            self._ensure_unique("observation", raw_observations)
            self._ensure_unique("finding", raw_findings)
            self._ensure_unique("hypothesis", raw_hypotheses)
            self._ensure_unique("investigation", raw_investigations)
            self._ensure_unique("timeline event", raw_timeline)
            self._ensure_unique("variant", raw_variants)
            self._ensure_unique("scoring rule", raw_rules)
            compiled = CompiledScenario(
                scenario=metadata,
                roles=[RoleDefinition.model_validate(item) for item in raw_roles],
                external_entities=[
                    ExternalEntityDefinition.model_validate(item)
                    for item in raw_external_entities
                ],
                observations=[
                    ObservationDefinition.model_validate(item)
                    for item in raw_observations
                ],
                findings=[
                    FindingDefinition.model_validate(item) for item in raw_findings
                ],
                hypotheses=[
                    HypothesisDefinition.model_validate(item)
                    for item in raw_hypotheses
                ],
                investigations=[
                    InvestigationDefinition.model_validate(item)
                    for item in raw_investigations
                ],
                timeline=[TimelineEvent.model_validate(item) for item in raw_timeline],
                variants=[VariantDefinition.model_validate(item) for item in raw_variants],
                scoring_rules=[ScoringRule.model_validate(item) for item in raw_rules],
            )
        except (KeyError, TypeError, ValidationError, yaml.YAMLError) as exc:
            raise ScenarioValidationError(str(exc)) from exc

        self._cross_validate(compiled)
        return compiled

    def materialize(
        self, compiled: CompiledScenario, variant_id: str
    ) -> RuntimeScenario:
        try:
            variant = compiled.variant(variant_id)
        except StopIteration as exc:
            raise ScenarioValidationError(f"unknown variant: {variant_id}") from exc

        observations = {
            item.id: item.model_copy(deep=True) for item in compiled.observations
        }
        timeline = {item.id: item.model_copy(deep=True) for item in compiled.timeline}
        try:
            for override in variant.observation_overrides:
                update = override.model_dump(
                    exclude={"observation_id"}, exclude_none=True
                )
                merged = observations[override.observation_id].model_dump()
                merged.update(update)
                observations[override.observation_id] = (
                    ObservationDefinition.model_validate(merged)
                )
            for override in variant.timeline_overrides:
                if not override.enabled:
                    timeline.pop(override.event_id, None)
                    continue
                update = override.model_dump(
                    exclude={"event_id", "enabled"}, exclude_none=True
                )
                merged = timeline[override.event_id].model_dump()
                merged.update(update)
                timeline[override.event_id] = TimelineEvent.model_validate(merged)
        except (KeyError, ValidationError) as exc:
            raise ScenarioValidationError(
                f"invalid overrides for variant {variant.id}: {exc}"
            ) from exc

        runtime = RuntimeScenario(
            scenario=compiled.scenario,
            roles=deepcopy(compiled.roles),
            external_entities=deepcopy(compiled.external_entities),
            observations=list(observations.values()),
            findings=deepcopy(compiled.findings),
            hypotheses=deepcopy(compiled.hypotheses),
            investigations=deepcopy(compiled.investigations),
            timeline=sorted(
                timeline.values(), key=lambda event: (event.at_minute, event.id)
            ),
            scoring_rules=deepcopy(compiled.scoring_rules),
            variant_id=variant.id,
            ground_truth=deepcopy(variant.ground_truth),
            investigation_outcomes=deepcopy(variant.investigation_outcomes),
        )
        self._validate_timeline(
            runtime.timeline,
            {role.id for role in runtime.roles},
            {item.id for item in runtime.observations},
            runtime.scenario.duration_minutes,
            context=f"variant {variant.id}",
        )
        return runtime

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"{path.name} must contain a mapping")
        return data

    @staticmethod
    def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = data[key]
        if not isinstance(value, list):
            raise TypeError(f"{key} must be a list")
        return value

    @staticmethod
    def _ensure_unique(kind: str, items: list[dict[str, Any]]) -> None:
        ids = [item.get("id") for item in items]
        duplicates = sorted(
            {item_id for item_id in ids if item_id is not None and ids.count(item_id) > 1}
        )
        if duplicates:
            raise ScenarioValidationError(
                f"duplicate {kind} IDs: {', '.join(duplicates)}"
            )

    def _cross_validate(self, compiled: CompiledScenario) -> None:
        role_ids = {role.id for role in compiled.roles}
        observation_ids = {item.id for item in compiled.observations}
        finding_ids = {item.id for item in compiled.findings}
        evidence_ids = observation_ids | finding_ids
        event_ids = {event.id for event in compiled.timeline}
        investigation_ids = {item.id for item in compiled.investigations}
        hypothesis_ids = {item.id for item in compiled.hypotheses}
        category_ids = [item.id for item in compiled.scenario.decision_categories]
        self._ensure_no_duplicate_values("decision category IDs", category_ids)
        self._ensure_no_duplicate_values(
            "hypothesis keys", [item.key for item in compiled.hypotheses]
        )
        decision_categories = set(category_ids)

        collisions = observation_ids & finding_ids
        if collisions:
            raise ScenarioValidationError(
                f"evidence IDs collide across observations and findings: {sorted(collisions)}"
            )

        for entity in compiled.external_entities:
            self._ensure_no_duplicate_values(
                f"external entity {entity.id} accepted communication types",
                entity.accepts,
            )

        for investigation in compiled.investigations:
            self._ensure_no_duplicate_values(
                f"investigation {investigation.id} performer roles",
                investigation.performer_roles,
            )
            self._ensure_no_duplicate_values(
                f"investigation {investigation.id} all-evidence prerequisites",
                investigation.prerequisites.all_evidence,
            )
            self._ensure_no_duplicate_values(
                f"investigation {investigation.id} any-evidence prerequisites",
                investigation.prerequisites.any_evidence,
            )
            unknown_roles = set(investigation.performer_roles) - role_ids
            if unknown_roles:
                raise ScenarioValidationError(
                    f"investigation {investigation.id} references unknown performer roles "
                    f"{sorted(unknown_roles)}"
                )
            prerequisites = {
                *investigation.prerequisites.all_evidence,
                *investigation.prerequisites.any_evidence,
            }
            unknown_evidence = prerequisites - evidence_ids
            if unknown_evidence:
                raise ScenarioValidationError(
                    f"investigation {investigation.id} prerequisites reference unknown "
                    f"evidence {sorted(unknown_evidence)}"
                )

        self._validate_timeline(
            compiled.timeline,
            role_ids,
            observation_ids,
            compiled.scenario.duration_minutes,
            context="base scenario",
        )

        for variant in compiled.variants:
            observation_override_ids = [
                item.observation_id for item in variant.observation_overrides
            ]
            event_override_ids = [item.event_id for item in variant.timeline_overrides]
            outcome_ids = [
                item.investigation_id for item in variant.investigation_outcomes
            ]
            self._ensure_no_duplicate_values(
                f"variant {variant.id} observation overrides",
                observation_override_ids,
            )
            self._ensure_no_duplicate_values(
                f"variant {variant.id} timeline overrides", event_override_ids
            )
            self._ensure_no_duplicate_values(
                f"variant {variant.id} investigation outcomes", outcome_ids
            )
            unknown_observations = set(observation_override_ids) - observation_ids
            if unknown_observations:
                raise ScenarioValidationError(
                    f"variant {variant.id} overrides unknown observations "
                    f"{sorted(unknown_observations)}"
                )
            unknown_events = set(event_override_ids) - event_ids
            if unknown_events:
                raise ScenarioValidationError(
                    f"variant {variant.id} overrides unknown events "
                    f"{sorted(unknown_events)}"
                )
            unknown_investigations = set(outcome_ids) - investigation_ids
            if unknown_investigations:
                raise ScenarioValidationError(
                    f"variant {variant.id} has outcomes for unknown investigations "
                    f"{sorted(unknown_investigations)}"
                )
            missing_outcomes = investigation_ids - set(outcome_ids)
            if missing_outcomes:
                raise ScenarioValidationError(
                    f"variant {variant.id} is missing investigation outcomes "
                    f"{sorted(missing_outcomes)}"
                )
            for override in variant.timeline_overrides:
                if override.role and override.role not in role_ids:
                    raise ScenarioValidationError(
                        f"variant {variant.id} references unknown role {override.role}"
                    )
                if override.observation_ids:
                    unknown = set(override.observation_ids) - observation_ids
                    if unknown:
                        raise ScenarioValidationError(
                            f"variant {variant.id} references unknown observations "
                            f"{sorted(unknown)}"
                        )
            for outcome in variant.investigation_outcomes:
                self._ensure_no_duplicate_values(
                    f"variant {variant.id} outcome {outcome.investigation_id} findings",
                    outcome.reveal_findings,
                )
                unknown_findings = set(outcome.reveal_findings) - finding_ids
                if unknown_findings:
                    raise ScenarioValidationError(
                        f"variant {variant.id} investigation {outcome.investigation_id} "
                        f"reveals unknown findings {sorted(unknown_findings)}"
                    )

        for rule in compiled.scoring_rules:
            referenced_evidence = {
                item
                for item in (
                    rule.trigger_evidence,
                    rule.evidence_id,
                    rule.confirmation_evidence,
                )
                if item
            }
            unknown_evidence = referenced_evidence - evidence_ids
            if unknown_evidence:
                raise ScenarioValidationError(
                    f"scoring rule {rule.id} references unknown evidence "
                    f"{sorted(unknown_evidence)}"
                )
            if rule.target_role and rule.target_role not in role_ids:
                raise ScenarioValidationError(
                    f"scoring rule {rule.id} references unknown role {rule.target_role}"
                )
            if (
                rule.decision_category
                and rule.decision_category not in decision_categories
            ):
                raise ScenarioValidationError(
                    f"scoring rule {rule.id} references unknown decision category "
                    f"{rule.decision_category}"
                )
            if rule.hypothesis_id and rule.hypothesis_id not in hypothesis_ids:
                raise ScenarioValidationError(
                    f"scoring rule {rule.id} references unknown hypothesis "
                    f"{rule.hypothesis_id}"
                )

        for variant in compiled.variants:
            self.materialize(compiled, variant.id)

    @staticmethod
    def _validate_timeline(
        timeline: list[TimelineEvent],
        role_ids: set[str],
        observation_ids: set[str],
        duration: int,
        *,
        context: str,
    ) -> None:
        for event in timeline:
            if event.at_minute > duration:
                raise ScenarioValidationError(
                    f"{context} event {event.id} occurs after scenario duration"
                )
            if event.role not in role_ids:
                raise ScenarioValidationError(
                    f"event {event.id} references unknown role {event.role}"
                )
            unknown = set(event.observation_ids) - observation_ids
            if unknown:
                raise ScenarioValidationError(
                    f"event {event.id} references unknown observations {sorted(unknown)}"
                )
            if len(event.observation_ids) != len(set(event.observation_ids)):
                raise ScenarioValidationError(
                    f"event {event.id} contains duplicate observation references"
                )

    @staticmethod
    def _ensure_no_duplicate_values(kind: str, values: list[str]) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ScenarioValidationError(f"duplicate {kind}: {', '.join(duplicates)}")
