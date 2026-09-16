from pathlib import Path
from shutil import copytree
from stat import S_IMODE

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.domain.scenarios.compiler import ScenarioValidationError
from app.llm.fake_provider import FakeLLMProvider
from app.services.scenario_registry import ScenarioRegistry


CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"
REQUIRED_FILES = {"definition.yaml", "variants.yaml"}


def registry_copy(tmp_path: Path) -> ScenarioRegistry:
    content_root = tmp_path / "content"
    copytree(CONTENT_ROOT, content_root)
    registry = ScenarioRegistry(content_root / "scenarios")
    registry.load()
    return registry


def app_for(registry: ScenarioRegistry) -> FastAPI:
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.include_router(router)
    return app


def test_updates_complete_validated_source_set_and_reloads_registry(tmp_path: Path):
    registry = registry_copy(tmp_path)
    files = registry.source_files("ransomware_001")
    definition = yaml.safe_load(files["definition.yaml"])
    definition["scenario"]["description"] = "Coordinate a revised response"
    files["definition.yaml"] = yaml.safe_dump(definition, sort_keys=False)

    updated = registry.update_source_files("ransomware_001", files)

    assert set(files) == REQUIRED_FILES
    assert updated.scenario.description.startswith("Coordinate a revised response")
    assert registry.get("ransomware_001").scenario.description.startswith(
        "Coordinate a revised response"
    )


def test_update_preserves_source_file_permissions_and_ownership(tmp_path: Path):
    registry = registry_copy(tmp_path)
    definition_file = registry.root / "ransomware_001" / "definition.yaml"
    definition_file.chmod(0o640)
    original = definition_file.stat()

    registry.update_source_files(
        "ransomware_001",
        registry.source_files("ransomware_001"),
    )

    updated = definition_file.stat()
    assert S_IMODE(updated.st_mode) == S_IMODE(original.st_mode)
    assert updated.st_uid == original.st_uid
    assert updated.st_gid == original.st_gid


def test_invalid_source_does_not_change_files_or_registry(tmp_path: Path):
    registry = registry_copy(tmp_path)
    original = registry.source_files("ransomware_001")
    invalid = dict(original)
    definition = yaml.safe_load(invalid["definition.yaml"])
    definition["timeline"][0]["role"] = "arbitrary_file"
    invalid["definition.yaml"] = yaml.safe_dump(definition, sort_keys=False)

    with pytest.raises(ScenarioValidationError, match="unknown role arbitrary_file"):
        registry.update_source_files("ransomware_001", invalid)

    assert registry.source_files("ransomware_001") == original
    assert registry.get("ransomware_001").timeline[0].role == "soc"


def test_requires_exact_allow_list_and_preserves_scenario_id(tmp_path: Path):
    registry = registry_copy(tmp_path)
    files = registry.source_files("ransomware_001")
    missing = dict(files)
    missing.pop("definition.yaml")

    with pytest.raises(ScenarioValidationError, match="missing files: definition.yaml"):
        registry.update_source_files("ransomware_001", missing)

    unsafe = dict(files)
    unsafe.pop("definition.yaml")
    unsafe["../../outside.yaml"] = "scenario: {}"
    with pytest.raises(ScenarioValidationError, match="unexpected files"):
        registry.update_source_files("ransomware_001", unsafe)
    assert not (tmp_path / "outside.yaml").exists()

    renamed = dict(files)
    definition = yaml.safe_load(renamed["definition.yaml"])
    definition["scenario"]["id"] = "renamed_scenario"
    renamed["definition.yaml"] = yaml.safe_dump(definition, sort_keys=False)
    with pytest.raises(
        ScenarioValidationError,
        match="scenario.id must remain ransomware_001",
    ):
        registry.update_source_files("ransomware_001", renamed)


def test_scenario_sources_api_returns_two_files_and_validation_errors(tmp_path: Path):
    registry = registry_copy(tmp_path)

    with TestClient(app_for(registry)) as client:
        loaded = client.get("/scenarios/ransomware_001/sources")
        assert loaded.status_code == 200
        assert set(loaded.json()["files"]) == REQUIRED_FILES
        files = loaded.json()["files"]
        definition = yaml.safe_load(files["definition.yaml"])
        definition["scoring"][0]["trigger_evidence"] = "O999"
        files["definition.yaml"] = yaml.safe_dump(definition, sort_keys=False)
        rejected = client.put(
            "/scenarios/ransomware_001/sources",
            json={"files": files},
        )

    assert rejected.status_code == 422
    assert "unknown evidence" in rejected.json()["detail"]


def test_authoring_round_trip_preserves_catalog_refs_and_writes_overrides(
    tmp_path: Path,
):
    registry = registry_copy(tmp_path)
    original_catalog = (
        registry.catalog_root / "roles.yaml"
    ).read_text(encoding="utf-8")

    with TestClient(app_for(registry)) as client:
        loaded = client.get("/scenarios/ransomware_001/authoring")
        assert loaded.status_code == 200
        document = loaded.json()["document"]
        document["scenario"]["name"] = "Form-edited ransomware exercise"
        document["observations"][0]["statement"] = "Revised ambiguous signal."
        document["investigations"][0]["match_hints"].append(
            "trace authentication"
        )
        document["roles"][0]["communication_style"]["tone"] = "calm and technical"
        document["variants"][0]["investigation_outcomes"][0][
            "reveal_findings"
        ] = ["FD002"]

        saved = client.put(
            "/scenarios/ransomware_001/authoring",
            json={"document": document},
        )

    assert saved.status_code == 200
    files = registry.source_files("ransomware_001")
    definition = yaml.safe_load(files["definition.yaml"])
    assert "Revised ambiguous signal" in files["definition.yaml"]
    assert "trace authentication" in files["definition.yaml"]
    assert definition["participants"]["roles"][0] == {
        "ref": "soc",
        "overrides": {
            "communication_style": {"tone": "calm and technical"}
        },
    }
    assert "FD002" in files["variants.yaml"]
    assert (
        registry.catalog_root / "roles.yaml"
    ).read_text(encoding="utf-8") == original_catalog


def test_authoring_api_rejects_broken_cross_references(tmp_path: Path):
    registry = registry_copy(tmp_path)

    with TestClient(app_for(registry)) as client:
        document = client.get(
            "/scenarios/ransomware_001/authoring"
        ).json()["document"]
        document["investigations"][0]["prerequisites"]["all_evidence"] = [
            "FD999"
        ]
        rejected = client.put(
            "/scenarios/ransomware_001/authoring",
            json={"document": document},
        )

    assert rejected.status_code == 422
    assert "unknown evidence" in rejected.json()["detail"]
    assert registry.get("ransomware_001").investigations[0].id == "I001"


def test_registry_retains_previous_compiled_version_after_authoring_update(
    tmp_path: Path,
):
    registry = registry_copy(tmp_path)
    old_version = registry.version("ransomware_001")
    old_name = registry.get("ransomware_001").scenario.name
    document = registry.get("ransomware_001").model_copy(deep=True)
    document.scenario.name = "New published name"

    registry.update_document("ransomware_001", document)

    assert registry.version("ransomware_001") != old_version
    assert (
        registry.get_version("ransomware_001", old_version).scenario.name
        == old_name
    )
