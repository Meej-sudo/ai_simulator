from pathlib import Path
from shutil import copytree

import pytest
import yaml

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError


CONTENT = Path(__file__).resolve().parents[2] / "content"
SCENARIO = CONTENT / "scenarios" / "ransomware_001"
CATALOGS = CONTENT / "catalogs"


def compiler(catalogs: Path = CATALOGS) -> ScenarioCompiler:
    return ScenarioCompiler(catalogs)


def copy_content(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "content"
    copytree(CONTENT, target)
    return target / "scenarios" / "ransomware_001", target / "catalogs"


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def test_compiles_v2_bundle_catalog_references_and_deterministic_variants():
    compiled = compiler().compile(SCENARIO)

    assert {item.id for item in compiled.observations} == {
        "O001", "O002", "O003", "O004", "O005"
    }
    assert len(compiled.findings) == 12
    assert {item.id for item in compiled.hypotheses} == {
        "H001", "H002", "H003", "H004"
    }
    assert {item.id for item in compiled.investigations} == {
        "I001", "I002", "I003", "I004", "I005", "I006", "I007"
    }
    assert {item.id for item in compiled.roles} == {
        "soc", "ciso", "dpo", "ceo", "role_5"
    }
    assert {entity.id for entity in compiled.external_entities} == {
        "slovenian_dpa", "police", "press"
    }

    alpha = compiler().materialize(compiled, "track_alpha")
    bravo = compiler().materialize(compiled, "track_bravo")

    assert [item.model_dump() for item in alpha.observations] == [
        item.model_dump() for item in bravo.observations
    ]
    assert alpha.investigation_outcome("I004").reveal_findings == ["FD004"]
    assert bravo.investigation_outcome("I004").reveal_findings == ["FD010"]
    assert "ground_truth" not in alpha.model_dump()
    assert "investigation_outcomes" not in alpha.model_dump()


def test_v2_serialization_round_trips_without_domain_changes():
    scenario_compiler = compiler()
    original = scenario_compiler.compile(SCENARIO)
    definition = scenario_compiler.serialize_definition(original, SCENARIO)
    variants = scenario_compiler.serialize_variants(original)

    assert definition["participants"]["roles"][:4] == [
        "soc", "ciso", "dpo", "ceo"
    ]
    assert isinstance(definition["participants"]["roles"][4], dict)
    assert definition["participants"]["external_entities"] == [
        "slovenian_dpa", "police", "press"
    ]
    assert set(variants["variants"][0]["investigation_outcomes"]) == {
        item.id for item in original.investigations
    }


def test_rejects_wrong_schema_version_and_unknown_top_level_key(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["schema_version"] = 1
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="schema_version 2"):
        compiler(catalogs).compile(scenario)

    document["schema_version"] = 2
    document["unexpected"] = True
    dump(path, document)
    with pytest.raises(ScenarioValidationError, match="unexpected keys: unexpected"):
        compiler(catalogs).compile(scenario)


def test_rejects_duplicate_yaml_mapping_keys(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = catalogs / "roles.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nroles:\n  duplicate:\n    display_name: Duplicate\n",
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="duplicate mapping key: roles"):
        compiler(catalogs).compile(scenario)


def test_rejects_unknown_catalog_reference(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["participants"]["roles"].append("ghost")
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="unknown role catalog reference"):
        compiler(catalogs).compile(scenario)


def test_rejects_duplicate_evidence_ids(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["evidence"]["observations"].append(
        dict(document["evidence"]["observations"][0])
    )
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="duplicate observation IDs"):
        compiler(catalogs).compile(scenario)


def test_rejects_unknown_investigation_prerequisite(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["investigations"][0]["prerequisites"]["all_evidence"] = ["FD999"]
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="unknown evidence"):
        compiler(catalogs).compile(scenario)


def test_rejects_missing_variant_outcome(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "variants.yaml"
    document = load(path)
    document["variants"][0]["investigation_outcomes"].pop("I007")
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="missing investigation outcomes"):
        compiler(catalogs).compile(scenario)


def test_rejects_outcome_that_reveals_observation(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "variants.yaml"
    document = load(path)
    document["variants"][0]["investigation_outcomes"]["I001"][
        "reveal_findings"
    ] = ["O001"]
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="unknown findings"):
        compiler(catalogs).compile(scenario)


def test_rejects_unknown_timeline_role(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["timeline"][0]["role"] = "ghost"
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="unknown role ghost"):
        compiler(catalogs).compile(scenario)


def test_rejects_unknown_scoring_evidence(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = scenario / "definition.yaml"
    document = load(path)
    document["scoring"][0]["trigger_evidence"] = "O999"
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="unknown evidence"):
        compiler(catalogs).compile(scenario)


def test_rejects_duplicate_external_entity_accepts(tmp_path: Path):
    scenario, catalogs = copy_content(tmp_path)
    path = catalogs / "external_entities.yaml"
    document = load(path)
    accepts = document["external_entities"]["slovenian_dpa"]["accepts"]
    accepts.append(accepts[0])
    dump(path, document)

    with pytest.raises(ScenarioValidationError, match="accepted communication types"):
        compiler(catalogs).compile(scenario)
