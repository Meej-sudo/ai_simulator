from pathlib import Path
from shutil import copytree

import pytest

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError


SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "ransomware_001"


def test_compiles_example_and_materializes_deterministic_variants():
    compiler = ScenarioCompiler()
    compiled = compiler.compile(SCENARIO)

    assert compiled.scenario.id == "ransomware_001"
    assert {role.id for role in compiled.roles} == {"soc", "ciso", "dpo", "ceo"}
    assert {variant.id for variant in compiled.variants} == {
        "track_alpha",
        "track_bravo",
    }
    assert {item.id for item in compiled.scenario.decision_categories} == {
        "containment",
        "exfiltration",
        "notification",
    }

    alpha = compiler.materialize(compiled, "track_alpha")
    bravo = compiler.materialize(compiled, "track_bravo")

    assert alpha.ground_truth["data_exfiltration"] is True
    assert bravo.ground_truth["data_exfiltration"] is False
    assert {event.id for event in alpha.timeline} == {
        "E001", "E002", "E003", "E004", "E005", "E007"
    }
    assert "E007" not in {event.id for event in bravo.timeline}
    assert bravo.fact("F003").confidence.value == "low"


def test_rejects_duplicate_stable_ids(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    facts = scenario / "facts.yaml"
    facts.write_text(
        facts.read_text(encoding="utf-8")
        + "\n  - id: F001\n    type: observation\n    statement: duplicate\n",
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="duplicate fact IDs"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_timeline_role(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    timeline = scenario / "timeline.yaml"
    timeline.write_text(
        timeline.read_text(encoding="utf-8").replace("role: soc", "role: ghost", 1),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="unknown role ghost"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_scoring_fact(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    scoring = scenario / "scoring.yaml"
    scoring.write_text(
        scoring.read_text(encoding="utf-8").replace(
            "trigger_fact: F003", "trigger_fact: F999", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="unknown facts"):
        ScenarioCompiler().compile(scenario)


def test_rejects_invalid_variant_override(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    variants = scenario / "variants.yaml"
    variants.write_text(
        variants.read_text(encoding="utf-8").replace(
            "event_id: E006", "event_id: E999", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="overrides unknown events"):
        ScenarioCompiler().compile(scenario)


def test_rejects_variant_event_after_duration(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    variants = scenario / "variants.yaml"
    variants.write_text(
        variants.read_text(encoding="utf-8").replace("at_minute: 55", "at_minute: 999"),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="after scenario duration"):
        ScenarioCompiler().compile(scenario)


def test_rejects_unknown_scoring_decision_category(tmp_path: Path):
    scenario = tmp_path / "scenario"
    copytree(SCENARIO, scenario)
    scoring = scenario / "scoring.yaml"
    scoring.write_text(
        scoring.read_text(encoding="utf-8").replace(
            "decision_category: containment",
            "decision_category: hidden_answer",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScenarioValidationError, match="unknown decision category"):
        ScenarioCompiler().compile(scenario)
