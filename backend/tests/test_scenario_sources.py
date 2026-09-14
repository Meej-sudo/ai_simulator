from pathlib import Path
from shutil import copytree
from stat import S_IMODE

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.domain.scenarios.compiler import ScenarioValidationError
from app.llm.fake_provider import FakeLLMProvider
from app.services.scenario_registry import ScenarioRegistry


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "scenarios"
REQUIRED_FILES = {
    "scenario.yaml",
    "roles.yaml",
    "facts.yaml",
    "timeline.yaml",
    "variants.yaml",
    "scoring.yaml",
}


def registry_copy(tmp_path: Path) -> ScenarioRegistry:
    scenario_root = tmp_path / "scenarios"
    copytree(SOURCE_ROOT, scenario_root)
    registry = ScenarioRegistry(scenario_root)
    registry.load()
    return registry


def test_updates_complete_validated_source_set_and_reloads_registry(tmp_path: Path):
    registry = registry_copy(tmp_path)
    files = registry.source_files("ransomware_001")
    files["scenario.yaml"] = files["scenario.yaml"].replace(
        "Coordinate investigation, escalation, privacy response, and executive decisions",
        "Coordinate a revised response",
    )

    updated = registry.update_source_files("ransomware_001", files)

    assert set(files) == REQUIRED_FILES
    assert updated.scenario.description.startswith("Coordinate a revised response")
    assert registry.get("ransomware_001").scenario.description.startswith(
        "Coordinate a revised response"
    )


def test_update_preserves_source_file_permissions_and_ownership(tmp_path: Path):
    registry = registry_copy(tmp_path)
    scenario_file = registry.root / "ransomware_001" / "scenario.yaml"
    scenario_file.chmod(0o640)
    original = scenario_file.stat()
    files = registry.source_files("ransomware_001")

    registry.update_source_files("ransomware_001", files)

    updated = scenario_file.stat()
    assert S_IMODE(updated.st_mode) == S_IMODE(original.st_mode)
    assert updated.st_uid == original.st_uid
    assert updated.st_gid == original.st_gid


def test_invalid_source_does_not_change_files_or_registry(tmp_path: Path):
    registry = registry_copy(tmp_path)
    original = registry.source_files("ransomware_001")
    invalid = dict(original)
    invalid["timeline.yaml"] = invalid["timeline.yaml"].replace(
        "role: soc", "role: arbitrary_file", 1
    )

    with pytest.raises(ScenarioValidationError, match="unknown role arbitrary_file"):
        registry.update_source_files("ransomware_001", invalid)

    assert registry.source_files("ransomware_001") == original
    assert registry.get("ransomware_001").timeline[0].role == "soc"


def test_requires_exact_allow_list_and_preserves_scenario_id(tmp_path: Path):
    registry = registry_copy(tmp_path)
    files = registry.source_files("ransomware_001")
    missing = dict(files)
    missing.pop("facts.yaml")

    with pytest.raises(ScenarioValidationError, match="missing files: facts.yaml"):
        registry.update_source_files("ransomware_001", missing)

    unsafe = dict(files)
    unsafe.pop("roles.yaml")
    unsafe["../../outside.yaml"] = "roles: []"
    with pytest.raises(ScenarioValidationError, match="unexpected files"):
        registry.update_source_files("ransomware_001", unsafe)
    assert not (tmp_path / "outside.yaml").exists()

    renamed = dict(files)
    renamed["scenario.yaml"] = renamed["scenario.yaml"].replace(
        "id: ransomware_001", "id: renamed_scenario", 1
    )
    with pytest.raises(ScenarioValidationError, match="id must remain ransomware_001"):
        registry.update_source_files("ransomware_001", renamed)


def test_scenario_sources_api_returns_validation_errors(tmp_path: Path):
    registry = registry_copy(tmp_path)
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.include_router(router)

    with TestClient(app) as client:
        loaded = client.get("/scenarios/ransomware_001/sources")
        assert loaded.status_code == 200
        assert set(loaded.json()["files"]) == REQUIRED_FILES

        files = loaded.json()["files"]
        files["scoring.yaml"] = files["scoring.yaml"].replace(
            "trigger_fact: F003", "trigger_fact: F999", 1
        )
        rejected = client.put(
            "/scenarios/ransomware_001/sources",
            json={"files": files},
        )

    assert rejected.status_code == 422
    assert "unknown facts" in rejected.json()["detail"]


def test_authoring_api_round_trips_form_document_to_yaml(tmp_path: Path):
    registry = registry_copy(tmp_path)
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.include_router(router)

    with TestClient(app) as client:
        loaded = client.get("/scenarios/ransomware_001/authoring")
        assert loaded.status_code == 200
        document = loaded.json()["document"]
        document["scenario"]["name"] = "Form-edited ransomware exercise"
        document["roles"][0]["responsibilities"].append("preserve evidence")

        saved = client.put(
            "/scenarios/ransomware_001/authoring",
            json={"document": document},
        )

        assert saved.status_code == 200
        assert saved.json()["scenario"]["name"] == "Form-edited ransomware exercise"
        assert "preserve evidence" in saved.json()["document"]["roles"][0][
            "responsibilities"
        ]
        assert "Form-edited ransomware exercise" in registry.source_files(
            "ransomware_001"
        )["scenario.yaml"]


def test_authoring_api_rejects_broken_cross_references(tmp_path: Path):
    registry = registry_copy(tmp_path)
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.include_router(router)

    with TestClient(app) as client:
        loaded = client.get("/scenarios/ransomware_001/authoring")
        document = loaded.json()["document"]
        document["timeline"][0]["role"] = "missing_role"
        rejected = client.put(
            "/scenarios/ransomware_001/authoring",
            json={"document": document},
        )

    assert rejected.status_code == 422
    assert "unknown role missing_role" in rejected.json()["detail"]
    assert registry.get("ransomware_001").timeline[0].role == "soc"
