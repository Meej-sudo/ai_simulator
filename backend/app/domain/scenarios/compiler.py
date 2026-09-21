from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError
from yaml.constructor import ConstructorError

from .models import (
    AllTrigger,
    AnyTrigger,
    AssessmentExistsTrigger,
    CommunicationSentTrigger,
    CompiledScenario,
    DecisionRecordedTrigger,
    EventDefinition,
    EventFiredTrigger,
    EvidenceKnownTrigger,
    ExternalEntityDefinition,
    FindingDefinition,
    HypothesisDefinition,
    InvestigationDefinition,
    ObservationDefinition,
    OrganizationalPressureEventDefinition,
    RevealEvidenceEventDefinition,
    RevealFindingEffect,
    RevealObservationEffect,
    RoleDefinition,
    RuntimeScenario,
    ScenarioMetadata,
    ScoringRule,
    SimulationTimeTrigger,
    StakeholderInteractionEventDefinition,
    TimelineEvent,
    TriggerDefinition,
    VariantDefinition,
)


class ScenarioValidationError(ValueError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate mapping key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class ScenarioCompiler:
    SCHEMA_VERSION = 2
    REQUIRED_FILES = ("definition.yaml", "variants.yaml")
    LEGACY_REQUIRED_FILES = (
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

    def __init__(self, catalog_root: str | Path | None = None):
        self.catalog_root = Path(catalog_root) if catalog_root else None

    def required_files_for(self, directory: str | Path) -> tuple[str, ...]:
        path = Path(directory)
        if (path / "definition.yaml").is_file():
            return self.REQUIRED_FILES
        return self.LEGACY_REQUIRED_FILES

    def compile(self, directory: str | Path) -> CompiledScenario:
        path = Path(directory)
        if (path / "definition.yaml").is_file():
            return self._compile_v2(path)
        return self._compile_legacy(path)

    def _compile_v2(self, path: Path) -> CompiledScenario:
        self._require_files(path, self.REQUIRED_FILES)
        try:
            definition = self._load(path / "definition.yaml")
            variants_document = self._load(path / "variants.yaml")
            self._require_keys(
                definition,
                {
                    "schema_version",
                    "scenario",
                    "participants",
                    "decision_categories",
                    "hypotheses",
                    "evidence",
                    "investigations",
                    "events",
                    "scoring",
                },
                context="definition.yaml",
            )
            self._require_keys(
                variants_document,
                {"schema_version", "scenario_id", "variants"},
                context="variants.yaml",
            )
            self._require_schema_version(definition, "definition.yaml")
            self._require_schema_version(variants_document, "variants.yaml")

            raw_metadata = self._mapping(definition, "scenario")
            self._require_keys(
                raw_metadata,
                {"id", "name", "description", "duration_minutes"},
                context="definition.yaml scenario",
            )
            raw_metadata = {
                **raw_metadata,
                "decision_categories": self._list(
                    definition, "decision_categories"
                ),
            }
            metadata = ScenarioMetadata.model_validate(raw_metadata)
            if variants_document["scenario_id"] != metadata.id:
                raise ScenarioValidationError(
                    "variants.yaml scenario_id must match definition.yaml scenario.id"
                )

            participants = self._mapping(definition, "participants")
            self._require_keys(
                participants,
                {"roles", "external_entities"},
                context="definition.yaml participants",
            )
            raw_roles = self._list_any(participants, "roles")
            if not all(isinstance(item, str) for item in raw_roles):
                raise ScenarioValidationError(
                    "definition.yaml participants.roles must contain only role "
                    "catalog IDs"
                )
            roles = self._resolve_roles(raw_roles, path)
            external_entities = self._resolve_external_entities(
                self._list_any(participants, "external_entities"),
                path,
            )

            evidence = self._mapping(definition, "evidence")
            self._require_keys(
                evidence,
                {"observations", "findings"},
                context="definition.yaml evidence",
            )
            raw_observations = self._list(evidence, "observations")
            raw_findings = self._list(evidence, "findings")
            raw_hypotheses = self._list(definition, "hypotheses")
            raw_investigations = self._list(definition, "investigations")
            raw_rules = self._list(definition, "scoring")

            raw_timeline = [
                self._normalize_event(item)
                for item in self._list(definition, "events")
            ]

            raw_variants: list[dict[str, Any]] = []
            for item in self._list(variants_document, "variants"):
                self._require_keys(
                    item,
                    {"id", "name", "ground_truth", "investigation_outcomes"},
                    {
                        "observation_overrides",
                        "event_overrides",
                    },
                    context=f"variant {item.get('id', '<unknown>')}",
                )
                outcomes = item["investigation_outcomes"]
                if not isinstance(outcomes, dict):
                    raise TypeError("investigation_outcomes must be a mapping")
                raw_outcomes = []
                for investigation_id, outcome in outcomes.items():
                    self._require_keys(
                        outcome,
                        {"reveal_findings"},
                        context=(
                            f"variant {item.get('id', '<unknown>')} outcome "
                            f"{investigation_id}"
                        ),
                    )
                    raw_outcomes.append(
                        {
                            "investigation_id": investigation_id,
                            "reveal_findings": outcome["reveal_findings"],
                        }
                    )
                raw_variants.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "ground_truth": item["ground_truth"],
                        "observation_overrides": item.get(
                            "observation_overrides", []
                        ),
                        "timeline_overrides": item.get("event_overrides", []),
                        "investigation_outcomes": raw_outcomes,
                    }
                )

            compiled = self._build_compiled(
                metadata=metadata,
                roles=roles,
                external_entities=external_entities,
                raw_observations=raw_observations,
                raw_findings=raw_findings,
                raw_hypotheses=raw_hypotheses,
                raw_investigations=raw_investigations,
                raw_timeline=raw_timeline,
                raw_variants=raw_variants,
                raw_rules=raw_rules,
            )
        except ScenarioValidationError:
            raise
        except (KeyError, TypeError, ValidationError, yaml.YAMLError) as exc:
            raise ScenarioValidationError(str(exc)) from exc

        self._cross_validate(compiled)
        return compiled

    def _compile_legacy(self, path: Path) -> CompiledScenario:
        self._require_files(path, self.LEGACY_REQUIRED_FILES)
        try:
            metadata = ScenarioMetadata.model_validate(
                self._load(path / "scenario.yaml")["scenario"]
            )
            raw_roles = self._list(self._load(path / "roles.yaml"), "roles")
            raw_external_entities = self._list(
                self._load(path / "external_entities.yaml"), "external_entities"
            )
            evidence = self._load(path / "evidence.yaml")
            compiled = self._build_compiled(
                metadata=metadata,
                roles=self._legacy_roles(raw_roles, path),
                external_entities=[
                    ExternalEntityDefinition.model_validate(item)
                    for item in raw_external_entities
                ],
                raw_observations=self._list(evidence, "observations"),
                raw_findings=self._list(evidence, "findings"),
                raw_hypotheses=self._list(
                    self._load(path / "hypotheses.yaml"), "hypotheses"
                ),
                raw_investigations=self._list(
                    self._load(path / "investigations.yaml"), "investigations"
                ),
                raw_timeline=self._list(
                    self._load(path / "timeline.yaml"), "events"
                ),
                raw_variants=self._list(
                    self._load(path / "variants.yaml"), "variants"
                ),
                raw_rules=self._list(
                    self._load(path / "scoring.yaml"), "rules"
                ),
            )
        except ScenarioValidationError:
            raise
        except (KeyError, TypeError, ValidationError, yaml.YAMLError) as exc:
            raise ScenarioValidationError(str(exc)) from exc

        self._cross_validate(compiled)
        return compiled

    def _legacy_roles(
        self, items: list[dict[str, Any]], scenario_directory: Path
    ) -> list[RoleDefinition]:
        catalog: dict[str, RoleDefinition] = {}
        if self.catalog_root is not None:
            catalog = self._role_catalog(scenario_directory)
        neutral_personality = {
            "summary": "Professional and focused on the role responsibilities.",
            "traits": {
                "openness": "medium",
                "conscientiousness": "medium",
                "extraversion": "medium",
                "agreeableness": "medium",
                "emotional_stability": "medium",
            },
            "behavioral_tendencies": [
                "Communicate clearly and identify missing information."
            ],
            "under_pressure": (
                "Remain professional and focus on the next useful action."
            ),
        }
        roles = []
        for item in items:
            value = deepcopy(item)
            if "personality" not in value:
                catalog_role = catalog.get(value.get("id"))
                value["personality"] = (
                    catalog_role.personality.model_dump(mode="json")
                    if catalog_role is not None
                    else deepcopy(neutral_personality)
                )
            roles.append(RoleDefinition.model_validate(value))
        return roles

    @classmethod
    def _normalize_event(cls, item: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(item)
        if value.get("type") == "observation_grant" or (
            "at_minute" in value and "role" in value
            and ("observation_ids" in value or "reveal_observations" in value)
        ):
            observations = value.get("observation_ids", value.get("reveal_observations", []))
            return {
                "id": value["id"],
                "type": "reveal_evidence",
                "trigger": {
                    "type": "simulation_time",
                    "at_minute": value["at_minute"],
                },
                "effects": [
                    {
                        "type": "reveal_observation",
                        "role_id": value["role"],
                        "observation_id": observation_id,
                    }
                    for observation_id in observations
                ],
                "once": True,
            }
        if value.get("type") == "reveal_evidence":
            legacy_role = value.pop("role", None)
            legacy_minute = value.pop("at_minute", None)
            legacy_observations = value.pop(
                "observation_ids", value.pop("reveal_observations", None)
            )
            if legacy_minute is not None:
                value.setdefault("trigger", {})["at_minute"] = legacy_minute
            if legacy_role is not None:
                for effect in value.get("effects", []):
                    effect["role_id"] = legacy_role
            if legacy_observations is not None:
                roles = {
                    effect.get("role_id") for effect in value.get("effects", [])
                }
                role_id = legacy_role or (next(iter(roles)) if len(roles) == 1 else None)
                value["effects"] = [
                    {
                        "type": "reveal_observation",
                        "role_id": role_id,
                        "observation_id": observation_id,
                    }
                    for observation_id in legacy_observations
                ]
        trigger = value.get("trigger")
        if isinstance(trigger, dict):
            value["trigger"] = cls._normalize_trigger(trigger)
        return value

    @classmethod
    def _normalize_trigger(cls, trigger: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(trigger)
        if "type" not in value:
            composite = [name for name in ("all", "any") if name in value]
            if len(composite) != 1:
                raise ScenarioValidationError(
                    "event trigger must define a type, all, or any"
                )
            name = composite[0]
            value = {"type": name, "triggers": value[name]}
        if value.get("type") in {"all", "any"}:
            children = value.get("triggers", value.get(value["type"]))
            if not isinstance(children, list):
                raise ScenarioValidationError("composite event trigger must contain a list")
            value = {
                "type": value["type"],
                "triggers": [cls._normalize_trigger(child) for child in children],
            }
        return value

    def _build_compiled(
        self,
        *,
        metadata: ScenarioMetadata,
        roles: list[RoleDefinition],
        external_entities: list[ExternalEntityDefinition],
        raw_observations: list[dict[str, Any]],
        raw_findings: list[dict[str, Any]],
        raw_hypotheses: list[dict[str, Any]],
        raw_investigations: list[dict[str, Any]],
        raw_timeline: list[dict[str, Any]],
        raw_variants: list[dict[str, Any]],
        raw_rules: list[dict[str, Any]],
    ) -> CompiledScenario:
        collections = (
            ("role", [item.model_dump() for item in roles]),
            (
                "external entity",
                [item.model_dump() for item in external_entities],
            ),
            ("observation", raw_observations),
            ("finding", raw_findings),
            ("hypothesis", raw_hypotheses),
            ("investigation", raw_investigations),
            ("timeline event", raw_timeline),
            ("variant", raw_variants),
            ("scoring rule", raw_rules),
        )
        for kind, items in collections:
            self._ensure_unique(kind, items)

        return CompiledScenario(
            scenario=metadata,
            roles=roles,
            external_entities=external_entities,
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
            events=[
                TypeAdapter(EventDefinition).validate_python(
                    self._normalize_event(item)
                )
                for item in raw_timeline
            ],
            variants=[
                VariantDefinition.model_validate(item) for item in raw_variants
            ],
            scoring_rules=[
                ScoringRule.model_validate(item) for item in raw_rules
            ],
        )

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
        events = {item.id: item.model_copy(deep=True) for item in compiled.events}
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
                    events.pop(override.event_id, None)
                    continue
                definition = events[override.event_id]
                if not isinstance(definition, RevealEvidenceEventDefinition):
                    raise ScenarioValidationError(
                        f"variant {variant.id} legacy event override can only target reveal events"
                    )
                if not isinstance(definition.trigger, SimulationTimeTrigger):
                    raise ScenarioValidationError(
                        f"variant {variant.id} cannot time-override a non-time event"
                    )
                merged = definition.model_dump(mode="json")
                if override.at_minute is not None:
                    merged["trigger"]["at_minute"] = override.at_minute
                if override.role is not None:
                    for effect in merged["effects"]:
                        effect["role_id"] = override.role
                if override.observation_ids is not None:
                    roles = {effect["role_id"] for effect in merged["effects"]}
                    if len(roles) != 1:
                        raise ScenarioValidationError(
                            f"variant {variant.id} cannot replace observations for a multi-role event"
                        )
                    role_id = next(iter(roles))
                    merged["effects"] = [
                        {
                            "type": "reveal_observation",
                            "role_id": role_id,
                            "observation_id": observation_id,
                        }
                        for observation_id in override.observation_ids
                    ]
                events[override.event_id] = TypeAdapter(EventDefinition).validate_python(merged)
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
            events=list(events.values()),
            scoring_rules=deepcopy(compiled.scoring_rules),
            variant_id=variant.id,
            ground_truth=deepcopy(variant.ground_truth),
            investigation_outcomes=deepcopy(variant.investigation_outcomes),
        )
        self._validate_events(
            runtime.events,
            {role.id for role in runtime.roles},
            {entity.id for entity in runtime.external_entities},
            {item.id for item in runtime.observations},
            {item.id for item in runtime.findings},
            {item.id for item in runtime.hypotheses},
            {item.id for item in runtime.scenario.decision_categories},
            runtime.scenario.duration_minutes,
            context=f"variant {variant.id}",
        )
        return runtime

    def serialize_definition(
        self,
        compiled: CompiledScenario,
        scenario_directory: str | Path,
        role_catalog: dict[str, RoleDefinition] | None = None,
    ) -> dict[str, Any]:
        path = Path(scenario_directory)
        if role_catalog is None:
            role_catalog = self._role_catalog(path)
        entity_catalog = self._external_entity_catalog(path)
        scenario = compiled.scenario.model_dump(
            mode="json",
            exclude={"decision_categories"},
            exclude_none=True,
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "scenario": scenario,
            "participants": {
                "roles": [
                    self._serialize_role_reference(item, role_catalog)
                    for item in compiled.roles
                ],
                "external_entities": [
                    self._serialize_catalog_item(item, entity_catalog)
                    for item in compiled.external_entities
                ],
            },
            "decision_categories": [
                item.model_dump(mode="json", exclude_none=True)
                for item in compiled.scenario.decision_categories
            ],
            "hypotheses": [
                item.model_dump(mode="json", exclude_none=True)
                for item in compiled.hypotheses
            ],
            "evidence": {
                "observations": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in compiled.observations
                ],
                "findings": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in compiled.findings
                ],
            },
            "investigations": [
                item.model_dump(mode="json", exclude_none=True)
                for item in compiled.investigations
            ],
            "events": [
                item.model_dump(mode="json", exclude_none=True)
                for item in compiled.events
            ],
            "scoring": [
                item.model_dump(mode="json", exclude_none=True)
                for item in compiled.scoring_rules
            ],
        }

    def serialize_variants(self, compiled: CompiledScenario) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "scenario_id": compiled.scenario.id,
            "variants": [
                {
                    "id": variant.id,
                    "name": variant.name,
                    "ground_truth": variant.ground_truth,
                    "observation_overrides": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in variant.observation_overrides
                    ],
                    "event_overrides": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in variant.timeline_overrides
                    ],
                    "investigation_outcomes": {
                        outcome.investigation_id: {
                            "reveal_findings": outcome.reveal_findings
                        }
                        for outcome in variant.investigation_outcomes
                    },
                }
                for variant in compiled.variants
            ],
        }

    @staticmethod
    def content_version(compiled: CompiledScenario) -> str:
        payload = json.dumps(
            compiled.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _resolve_roles(
        self, items: list[Any], scenario_directory: Path
    ) -> list[RoleDefinition]:
        return self._resolve_catalog_items(
            items,
            self._role_catalog(scenario_directory),
            RoleDefinition,
            "role",
        )

    def _resolve_external_entities(
        self, items: list[Any], scenario_directory: Path
    ) -> list[ExternalEntityDefinition]:
        return self._resolve_catalog_items(
            items,
            self._external_entity_catalog(scenario_directory),
            ExternalEntityDefinition,
            "external entity",
        )

    def _resolve_catalog_items(self, items, catalog, model, kind):
        resolved = []
        for item in items:
            if isinstance(item, str):
                reference = item
                overrides = {}
            elif isinstance(item, dict) and "ref" in item:
                self._require_keys(
                    item,
                    {"ref"},
                    {"overrides"},
                    context=f"{kind} reference",
                )
                reference = item["ref"]
                overrides = item.get("overrides", {})
                if not isinstance(overrides, dict):
                    raise TypeError(f"{kind} overrides must be a mapping")
            elif isinstance(item, dict):
                resolved.append(model.model_validate(item))
                continue
            else:
                raise TypeError(
                    f"{kind} participant must be a catalog ID or mapping"
                )
            try:
                base = catalog[reference].model_dump(mode="json")
            except KeyError as exc:
                raise ScenarioValidationError(
                    f"unknown {kind} catalog reference: {reference}"
                ) from exc
            resolved.append(
                model.model_validate(self._deep_merge(base, overrides))
            )
        return resolved

    def _role_catalog(
        self, scenario_directory: Path
    ) -> dict[str, RoleDefinition]:
        raw = self._load_catalog(scenario_directory, "roles.yaml", "roles")
        return {
            item_id: RoleDefinition.model_validate({"id": item_id, **value})
            for item_id, value in raw.items()
        }

    def _external_entity_catalog(
        self, scenario_directory: Path
    ) -> dict[str, ExternalEntityDefinition]:
        raw = self._load_catalog(
            scenario_directory,
            "external_entities.yaml",
            "external_entities",
        )
        return {
            item_id: ExternalEntityDefinition.model_validate(
                {"id": item_id, **value}
            )
            for item_id, value in raw.items()
        }

    def _load_catalog(
        self,
        scenario_directory: Path,
        filename: str,
        key: str,
    ) -> dict[str, dict[str, Any]]:
        root = self.catalog_root or scenario_directory.parent.parent / "catalogs"
        path = root / filename
        if not path.is_file():
            raise ScenarioValidationError(f"missing catalog file: {path}")
        document = self._load(path)
        self._require_keys(
            document,
            {"schema_version", key},
            context=filename,
        )
        self._require_schema_version(document, filename)
        values = document[key]
        if not isinstance(values, dict):
            raise TypeError(f"{filename} {key} must be a mapping")
        for item_id, value in values.items():
            if not isinstance(value, dict):
                raise TypeError(f"{filename} entry {item_id} must be a mapping")
        return values

    @staticmethod
    def _serialize_role_reference(
        item: RoleDefinition, catalog: dict[str, RoleDefinition]
    ) -> str:
        catalog_item = catalog.get(item.id)
        if catalog_item is None:
            raise ScenarioValidationError(
                f"role {item.id} is not defined in the shared roles catalog"
            )
        if item.model_dump(mode="json") != catalog_item.model_dump(mode="json"):
            raise ScenarioValidationError(
                f"role {item.id} differs from the shared roles catalog"
            )
        return item.id

    @staticmethod
    def _serialize_catalog_item(item, catalog):
        current = item.model_dump(mode="json")
        catalog_item = catalog.get(item.id)
        if catalog_item is None:
            return item.model_dump(mode="json", exclude_none=True)
        base = catalog_item.model_dump(mode="json")
        if current == base:
            return item.id
        changes = ScenarioCompiler._deep_changes(base, current)
        changes.pop("id", None)
        return {"ref": item.id, "overrides": changes}

    @staticmethod
    def _deep_changes(base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        changes = {}
        for key, value in current.items():
            base_value = base.get(key)
            if isinstance(value, dict) and isinstance(base_value, dict):
                nested = ScenarioCompiler._deep_changes(base_value, value)
                if nested:
                    changes[key] = nested
            elif value != base_value:
                changes[key] = value
        return changes

    @staticmethod
    def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in overrides.items():
            if (
                isinstance(value, dict)
                and isinstance(merged.get(key), dict)
            ):
                merged[key] = ScenarioCompiler._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        if not isinstance(data, dict):
            raise TypeError(f"{path.name} must contain a mapping")
        return data

    @staticmethod
    def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data[key]
        if not isinstance(value, dict):
            raise TypeError(f"{key} must be a mapping")
        return value

    @staticmethod
    def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = data[key]
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise TypeError(f"{key} must be a list of mappings")
        return value

    @staticmethod
    def _list_any(data: dict[str, Any], key: str) -> list[Any]:
        value = data[key]
        if not isinstance(value, list):
            raise TypeError(f"{key} must be a list")
        return value

    @staticmethod
    def _require_files(path: Path, names: tuple[str, ...]) -> None:
        missing = [name for name in names if not (path / name).is_file()]
        if missing:
            raise ScenarioValidationError(
                f"missing scenario files: {', '.join(missing)}"
            )

    def _require_schema_version(
        self, document: dict[str, Any], filename: str
    ) -> None:
        if document["schema_version"] != self.SCHEMA_VERSION:
            raise ScenarioValidationError(
                f"{filename} requires schema_version {self.SCHEMA_VERSION}"
            )

    @staticmethod
    def _require_keys(
        value: dict[str, Any],
        required: set[str],
        optional: set[str] | None = None,
        *,
        context: str,
    ) -> None:
        if not isinstance(value, dict):
            raise TypeError(f"{context} must be a mapping")
        optional = optional or set()
        present = set(value)
        missing = sorted(required - present)
        unexpected = sorted(present - required - optional)
        problems = []
        if missing:
            problems.append(f"missing keys: {', '.join(missing)}")
        if unexpected:
            problems.append(f"unexpected keys: {', '.join(unexpected)}")
        if problems:
            raise ScenarioValidationError(
                f"{context}: {'; '.join(problems)}"
            )

    @staticmethod
    def _ensure_unique(kind: str, items: list[dict[str, Any]]) -> None:
        ids = [item.get("id") for item in items]
        duplicates = sorted(
            {
                item_id
                for item_id in ids
                if item_id is not None and ids.count(item_id) > 1
            }
        )
        if duplicates:
            raise ScenarioValidationError(
                f"duplicate {kind} IDs: {', '.join(duplicates)}"
            )

    def _cross_validate(self, compiled: CompiledScenario) -> None:
        role_ids = {role.id for role in compiled.roles}
        external_entity_ids = {entity.id for entity in compiled.external_entities}
        observation_ids = {item.id for item in compiled.observations}
        finding_ids = {item.id for item in compiled.findings}
        evidence_ids = observation_ids | finding_ids
        event_ids = {event.id for event in compiled.events}
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

        self._validate_events(
            compiled.events,
            role_ids,
            external_entity_ids,
            observation_ids,
            finding_ids,
            hypothesis_ids,
            decision_categories,
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

    @classmethod
    def _validate_events(
        cls,
        events: list[EventDefinition],
        role_ids: set[str],
        external_entity_ids: set[str],
        observation_ids: set[str],
        finding_ids: set[str],
        hypothesis_ids: set[str],
        decision_categories: set[str],
        duration: int,
        *,
        context: str,
    ) -> None:
        event_ids = {event.id for event in events}
        evidence_ids = observation_ids | finding_ids
        for event in events:
            cls._validate_trigger(
                event.id,
                event.trigger,
                role_ids,
                evidence_ids,
                hypothesis_ids,
                decision_categories,
                event_ids,
                duration,
                context=context,
            )
            if isinstance(event, RevealEvidenceEventDefinition):
                seen: set[tuple[str, str, str]] = set()
                for effect in event.effects:
                    if effect.role_id not in role_ids:
                        raise ScenarioValidationError(
                            f"event {event.id} references unknown role {effect.role_id}"
                        )
                    if isinstance(effect, RevealObservationEffect):
                        if effect.observation_id not in observation_ids:
                            raise ScenarioValidationError(
                                f"event {event.id} references unknown observation {effect.observation_id}"
                            )
                        key = (effect.type, effect.role_id, effect.observation_id)
                    else:
                        if effect.finding_id not in finding_ids:
                            raise ScenarioValidationError(
                                f"event {event.id} references unknown finding {effect.finding_id}"
                            )
                        key = (effect.type, effect.role_id, effect.finding_id)
                    if key in seen:
                        raise ScenarioValidationError(
                            f"event {event.id} contains duplicate effects"
                        )
                    seen.add(key)
            elif isinstance(event, OrganizationalPressureEventDefinition):
                if (
                    event.source.kind == "role"
                    and event.source.id not in role_ids
                ):
                    raise ScenarioValidationError(
                        f"event {event.id} references unknown pressure source role {event.source.id}"
                    )
                if (
                    event.source.kind == "external_entity"
                    and event.source.id not in external_entity_ids
                ):
                    raise ScenarioValidationError(
                        f"event {event.id} references unknown pressure source external entity {event.source.id}"
                    )
            elif isinstance(event, StakeholderInteractionEventDefinition):
                if event.actor_role not in role_ids:
                    raise ScenarioValidationError(
                        f"event {event.id} references unknown actor role {event.actor_role}"
                    )
                cls._ensure_no_duplicate_values(
                    f"event {event.id} follow-up IDs",
                    [item.id for item in event.follow_ups],
                )
                for follow_up in event.follow_ups:
                    condition = follow_up.when
                    if condition.trainee_assessment.hypothesis_id not in hypothesis_ids:
                        raise ScenarioValidationError(
                            f"event {event.id} follow-up {follow_up.id} references unknown hypothesis "
                            f"{condition.trainee_assessment.hypothesis_id}"
                        )
                    unknown = set(condition.evidence_support.confirmation_evidence_ids) - evidence_ids
                    if unknown:
                        raise ScenarioValidationError(
                            f"event {event.id} follow-up {follow_up.id} references unknown evidence "
                            f"{sorted(unknown)}"
                        )

    @classmethod
    def _validate_trigger(
        cls,
        event_id: str,
        trigger: TriggerDefinition,
        role_ids: set[str],
        evidence_ids: set[str],
        hypothesis_ids: set[str],
        decision_categories: set[str],
        event_ids: set[str],
        duration: int,
        *,
        context: str,
    ) -> None:
        if isinstance(trigger, SimulationTimeTrigger):
            if trigger.at_minute > duration:
                raise ScenarioValidationError(
                    f"{context} event {event_id} occurs after scenario duration"
                )
        elif isinstance(trigger, AssessmentExistsTrigger):
            if trigger.hypothesis_id not in hypothesis_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown hypothesis {trigger.hypothesis_id}"
                )
            if trigger.actor_role is not None and trigger.actor_role not in role_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown role {trigger.actor_role}"
                )
        elif isinstance(trigger, EvidenceKnownTrigger):
            if trigger.role_id not in role_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown role {trigger.role_id}"
                )
            if trigger.evidence_id not in evidence_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown evidence {trigger.evidence_id}"
                )
        elif isinstance(trigger, DecisionRecordedTrigger):
            if trigger.decision_category not in decision_categories:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown decision category {trigger.decision_category}"
                )
            if trigger.actor_role is not None and trigger.actor_role not in role_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown role {trigger.actor_role}"
                )
        elif isinstance(trigger, CommunicationSentTrigger):
            if trigger.role_id is not None and trigger.role_id not in role_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown role {trigger.role_id}"
                )
        elif isinstance(trigger, EventFiredTrigger):
            if trigger.event_id not in event_ids:
                raise ScenarioValidationError(
                    f"event {event_id} references unknown event {trigger.event_id}"
                )
            if trigger.event_id == event_id:
                raise ScenarioValidationError(
                    f"event {event_id} cannot trigger itself"
                )
        elif isinstance(trigger, (AllTrigger, AnyTrigger)):
            for child in trigger.triggers:
                cls._validate_trigger(
                    event_id,
                    child,
                    role_ids,
                    evidence_ids,
                    hypothesis_ids,
                    decision_categories,
                    event_ids,
                    duration,
                    context=context,
                )

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
