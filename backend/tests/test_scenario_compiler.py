from pathlib import Path
from shutil import copytree

import pytest
import yaml

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError


SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "ransomware_001"


def copy_scenario(tmp_path: Path) -> Path:
    target = tmp_path / "scenario"
    copytree(SCENARIO, target)
    return target


def test_compiles_sprint_one_concepts_and_deterministic_variants():
    compiler = ScenarioCompiler()
    compiled = compiler.compile(SCENARIO)

    assert compiled.scenario.id == "ransomware_001"
    assert {role.id for role in compiled.roles} == {"soc", "ciso", "dpo", "ceo"}
    assert compiled.role("soc").personality.traits.openness == "high"
    assert compiled.role("ceo").personality.traits.extraversion == "high"
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
    assert {entity.id for entity in compiled.external_entities} == {
        "slovenian_dpa", "police", "press"
    }

    alpha = compiler.materialize(compiled, "track_alpha")
    bravo = compiler.materialize(compiled, "track_bravo")

    assert [item.model_dump() for item in alpha.observations] == [
        item.model_dump() for item in bravo.observations
    ]
    assert [item.model_dump() for item in alpha.timeline] == [
        item.model_dump() for item in bravo.timeline
    ]
    assert alpha.investigation_outcome("I004").reveal_findings == ["FD004"]
    assert bravo.investigation_outcome("I004").reveal_findings == ["FD010"]
    assert alpha.ground_truth["data_exfiltration"] is True
    assert bravo.ground_truth["data_exfiltration"] is False
    assert "ground_truth" not in alpha.model_dump()
    assert "investigation_outcomes" not in alpha.model_dump()


def test_rejects_duplicate_evidence_ids(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "evidence.yaml"
    document = yaml.safe_load(path.read_text())
    document["observations"].append(dict(document["observations"][0]))
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(ScenarioValidationError, match="duplicate observation IDs"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_investigation_prerequisite(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "investigations.yaml"
    document = yaml.safe_load(path.read_text())
    document["investigations"][0]["prerequisites"]["all_evidence"] = ["FD999"]
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(ScenarioValidationError, match="unknown evidence"):
        ScenarioCompiler().compile(scenario)


def test_rejects_missing_variant_outcome(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "variants.yaml"
    document = yaml.safe_load(path.read_text())
    document["variants"][0]["investigation_outcomes"].pop()
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(ScenarioValidationError, match="missing investigation outcomes"):
        ScenarioCompiler().compile(scenario)


def test_rejects_outcome_that_reveals_observation(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "variants.yaml"
    document = yaml.safe_load(path.read_text())
    document["variants"][0]["investigation_outcomes"][0]["reveal_findings"] = ["O001"]
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(ScenarioValidationError, match="unknown findings"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_timeline_role(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "timeline.yaml"
    path.write_text(path.read_text().replace("role: soc", "role: ghost", 1))

    with pytest.raises(ScenarioValidationError, match="unknown role ghost"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_scoring_evidence(tmp_path: Path):
    scenario = copy_scenario(tmp_path)
    path = scenario / "scoring.yaml"
    path.write_text(path.read_text().replace("trigger_evidence: O004", "trigger_evidence: O999", 1))

    with pytest.raises(ScenarioValidationError, match="unknown evidence"):
        ScenarioCompiler().compile(scenario)


@pytest.mark.parametrize("field", ["id", "accepts"])
def test_rejects_duplicate_external_entity_identifiers(tmp_path: Path, field: str):
    scenario = copy_scenario(tmp_path)
    path = scenario / "external_entities.yaml"
    document = yaml.safe_load(path.read_text())
    if field == "id":
        document["external_entities"].append(dict(document["external_entities"][0]))
        message = "duplicate external entity IDs"
    else:
        document["external_entities"][0]["accepts"].append(
            document["external_entities"][0]["accepts"][0]
        )
        message = "accepted communication types"
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(ScenarioValidationError, match=message):
        ScenarioCompiler().compile(scenario)


def test_rejects_invalid_personality_trait(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    roles = scenario / "roles.yaml"
    roles.write_text(
        roles.read_text(encoding="utf-8").replace(
            "openness: high", "openness: extreme", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="literal_error"):
        ScenarioCompiler().compile(scenario)
