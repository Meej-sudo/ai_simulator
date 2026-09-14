from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import (
    CompiledScenario,
    FactDefinition,
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
        "facts.yaml",
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
            raw_facts = self._list(self._load(path / "facts.yaml"), "facts")
            raw_timeline = self._list(self._load(path / "timeline.yaml"), "events")
            raw_variants = self._list(self._load(path / "variants.yaml"), "variants")
            raw_rules = self._list(self._load(path / "scoring.yaml"), "rules")
            self._ensure_unique("role", raw_roles)
            self._ensure_unique("fact", raw_facts)
            self._ensure_unique("timeline event", raw_timeline)
            self._ensure_unique("variant", raw_variants)
            self._ensure_unique("scoring rule", raw_rules)
            compiled = CompiledScenario(
                scenario=metadata,
                roles=[RoleDefinition.model_validate(item) for item in raw_roles],
                facts=[FactDefinition.model_validate(item) for item in raw_facts],
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

        facts = {item.id: item.model_copy(deep=True) for item in compiled.facts}
        timeline = {item.id: item.model_copy(deep=True) for item in compiled.timeline}
        try:
            for override in variant.fact_overrides:
                update = override.model_dump(exclude={"fact_id"}, exclude_none=True)
                merged = facts[override.fact_id].model_dump()
                merged.update(update)
                facts[override.fact_id] = FactDefinition.model_validate(merged)
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
            facts=list(facts.values()),
            timeline=sorted(
                timeline.values(), key=lambda event: (event.at_minute, event.id)
            ),
            scoring_rules=deepcopy(compiled.scoring_rules),
            variant_id=variant.id,
            ground_truth=deepcopy(variant.ground_truth),
        )
        self._validate_timeline(
            runtime.timeline,
            {role.id for role in runtime.roles},
            {fact.id for fact in runtime.facts},
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
        fact_ids = {fact.id for fact in compiled.facts}
        event_ids = {event.id for event in compiled.timeline}
        category_ids = [item.id for item in compiled.scenario.decision_categories]
        self._ensure_no_duplicate_values("decision category IDs", category_ids)
        decision_categories = set(category_ids)

        self._validate_timeline(
            compiled.timeline,
            role_ids,
            fact_ids,
            compiled.scenario.duration_minutes,
            context="base scenario",
        )

        for variant in compiled.variants:
            fact_override_ids = [item.fact_id for item in variant.fact_overrides]
            event_override_ids = [item.event_id for item in variant.timeline_overrides]
            self._ensure_no_duplicate_values(
                f"variant {variant.id} fact overrides", fact_override_ids
            )
            self._ensure_no_duplicate_values(
                f"variant {variant.id} timeline overrides", event_override_ids
            )
            overridden_facts = set(fact_override_ids)
            overridden_events = set(event_override_ids)
            if overridden_facts - fact_ids:
                raise ScenarioValidationError(
                    f"variant {variant.id} overrides unknown facts "
                    f"{sorted(overridden_facts - fact_ids)}"
                )
            if overridden_events - event_ids:
                raise ScenarioValidationError(
                    f"variant {variant.id} overrides unknown events "
                    f"{sorted(overridden_events - event_ids)}"
                )
            for override in variant.timeline_overrides:
                if override.role and override.role not in role_ids:
                    raise ScenarioValidationError(
                        f"variant {variant.id} references unknown role {override.role}"
                    )
                if override.fact_ids and set(override.fact_ids) - fact_ids:
                    raise ScenarioValidationError(
                        f"variant {variant.id} references unknown facts "
                        f"{sorted(set(override.fact_ids) - fact_ids)}"
                    )

        for rule in compiled.scoring_rules:
            referenced_facts = {
                item
                for item in (rule.trigger_fact, rule.fact_id, rule.confirmation_fact)
                if item
            }
            if referenced_facts - fact_ids:
                raise ScenarioValidationError(
                    f"scoring rule {rule.id} references unknown facts "
                    f"{sorted(referenced_facts - fact_ids)}"
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
            if rule.type == "avoid_premature_conclusion":
                category = compiled.scenario.decision_category(
                    rule.decision_category or ""
                )
                if not category.captures_confidence:
                    raise ScenarioValidationError(
                        f"scoring rule {rule.id} requires confidence, but decision "
                        f"category {category.id} does not capture it"
                    )

        for variant in compiled.variants:
            self.materialize(compiled, variant.id)

    @staticmethod
    def _validate_timeline(
        timeline: list[TimelineEvent],
        role_ids: set[str],
        fact_ids: set[str],
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
            unknown = set(event.fact_ids) - fact_ids
            if unknown:
                raise ScenarioValidationError(
                    f"event {event.id} references unknown facts {sorted(unknown)}"
                )
            if len(event.fact_ids) != len(set(event.fact_ids)):
                raise ScenarioValidationError(
                    f"event {event.id} contains duplicate fact references"
                )

    @staticmethod
    def _ensure_no_duplicate_values(kind: str, values: list[str]) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ScenarioValidationError(f"duplicate {kind}: {', '.join(duplicates)}")
