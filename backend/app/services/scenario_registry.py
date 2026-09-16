import os
from pathlib import Path
from stat import S_IMODE
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import RLock

import yaml

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError
from app.domain.scenarios.models import (
    CompiledScenario,
    RoleDefinition,
    RuntimeScenario,
)


class ScenarioRegistry:
    MAX_SOURCE_BYTES = 512_000

    def __init__(self, root: str | Path, compiler: ScenarioCompiler | None = None):
        self.root = Path(root)
        self.catalog_root = self.root.parent / "catalogs"
        self.compiler = compiler or ScenarioCompiler(self.catalog_root)
        self._scenarios: dict[str, CompiledScenario] = {}
        self._directories: dict[str, Path] = {}
        self._versions: dict[tuple[str, str], CompiledScenario] = {}
        self._lock = RLock()

    def load(self) -> None:
        with self._lock:
            scenarios: dict[str, CompiledScenario] = {}
            directories: dict[str, Path] = {}
            versions = dict(self._versions)
            if not self.root.is_dir():
                raise ScenarioValidationError(
                    f"scenario root does not exist: {self.root}"
                )
            for directory in sorted(self.root.iterdir()):
                if not directory.is_dir():
                    continue
                if not (
                    (directory / "definition.yaml").is_file()
                    or (directory / "scenario.yaml").is_file()
                ):
                    continue
                compiled = self.compiler.compile(directory)
                scenario_id = compiled.scenario.id
                if scenario_id in scenarios:
                    raise ScenarioValidationError(
                        f"duplicate scenario ID: {scenario_id}"
                    )
                scenarios[scenario_id] = compiled
                directories[scenario_id] = directory
                versions[
                    (scenario_id, self.compiler.content_version(compiled))
                ] = compiled
            self._scenarios = scenarios
            self._directories = directories
            self._versions = versions

    def all(self) -> list[CompiledScenario]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> CompiledScenario:
        try:
            return self._scenarios[scenario_id]
        except KeyError as exc:
            raise KeyError(f"scenario not found: {scenario_id}") from exc

    def version(self, scenario_id: str) -> str:
        return self.compiler.content_version(self.get(scenario_id))

    def get_version(
        self, scenario_id: str, scenario_version: str
    ) -> CompiledScenario:
        try:
            return self._versions[(scenario_id, scenario_version)]
        except KeyError as exc:
            raise KeyError(
                f"scenario version not found: {scenario_id}@{scenario_version}"
            ) from exc

    def materialize(
        self,
        scenario_id: str,
        variant_id: str,
        scenario_version: str | None = None,
    ) -> RuntimeScenario:
        compiled = (
            self.get_version(scenario_id, scenario_version)
            if scenario_version
            else self.get(scenario_id)
        )
        return self.compiler.materialize(compiled, variant_id)

    def source_files(self, scenario_id: str) -> dict[str, str]:
        with self._lock:
            directory = self._directory(scenario_id)
            return {
                name: (directory / name).read_text(encoding="utf-8")
                for name in self.compiler.required_files_for(directory)
            }

    def update_document(
        self, scenario_id: str, document: CompiledScenario
    ) -> CompiledScenario:
        with self._lock:
            directory = self._directory(scenario_id)
            roles_path = self.catalog_root / "roles.yaml"
            entities_path = self.catalog_root / "external_entities.yaml"
            role_catalog_document = yaml.safe_load(
                roles_path.read_text(encoding="utf-8")
            )
            if not isinstance(role_catalog_document, dict) or not isinstance(
                role_catalog_document.get("roles"), dict
            ):
                raise ScenarioValidationError(
                    "roles.yaml roles must be a mapping"
                )

            catalog_values = role_catalog_document["roles"]
            for role in document.roles:
                catalog_values[role.id] = role.model_dump(
                    mode="json", exclude={"id"}, exclude_none=True
                )
            role_catalog = {
                role_id: RoleDefinition.model_validate(
                    {"id": role_id, **value}
                )
                for role_id, value in catalog_values.items()
            }
            role_catalog_content = self._dump_yaml(role_catalog_document)
            files = {
                "definition.yaml": self._dump_yaml(
                    self.compiler.serialize_definition(
                        document, directory, role_catalog=role_catalog
                    )
                ),
                "variants.yaml": self._dump_yaml(
                    self.compiler.serialize_variants(document)
                ),
            }

            for name, content in {
                "roles.yaml": role_catalog_content,
                **files,
            }.items():
                if len(content.encode("utf-8")) > self.MAX_SOURCE_BYTES:
                    raise ScenarioValidationError(
                        f"{name} exceeds the {self.MAX_SOURCE_BYTES}-byte limit"
                    )

            with TemporaryDirectory(prefix="scenario-form-editor-") as staging_name:
                staging_root = Path(staging_name)
                staging_catalogs = staging_root / "catalogs"
                staging_scenario = staging_root / "scenarios" / scenario_id
                staging_catalogs.mkdir(parents=True)
                staging_scenario.mkdir(parents=True)
                (staging_catalogs / "roles.yaml").write_text(
                    role_catalog_content, encoding="utf-8"
                )
                (staging_catalogs / "external_entities.yaml").write_text(
                    entities_path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                for name, content in files.items():
                    (staging_scenario / name).write_text(
                        content, encoding="utf-8"
                    )
                staged_compiler = ScenarioCompiler(staging_catalogs)
                compiled = staged_compiler.compile(staging_scenario)
                if compiled.scenario.id != scenario_id:
                    raise ScenarioValidationError(
                        f"definition.yaml scenario.id must remain {scenario_id}; "
                        f"received {compiled.scenario.id}"
                    )

            targets = {
                roles_path: role_catalog_content,
                **{directory / name: content for name, content in files.items()},
            }
            originals = {
                path: path.read_text(encoding="utf-8")
                if path.is_file()
                else None
                for path in targets
            }
            try:
                for path, content in targets.items():
                    self._atomic_write(path, content)
                self.load()
            except Exception:
                for path, content in originals.items():
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        self._atomic_write(path, content)
                self.load()
                raise
            return self.get(scenario_id)

    def update_source_files(
        self, scenario_id: str, files: dict[str, str]
    ) -> CompiledScenario:
        with self._lock:
            directory = self._directory(scenario_id)
            required = set(self.compiler.required_files_for(directory))
            supplied = set(files)
            if supplied != required:
                missing = sorted(required - supplied)
                unexpected = sorted(supplied - required)
                problems = []
                if missing:
                    problems.append(f"missing files: {', '.join(missing)}")
                if unexpected:
                    problems.append(f"unexpected files: {', '.join(unexpected)}")
                raise ScenarioValidationError("; ".join(problems))

            for name, content in files.items():
                if "\x00" in content:
                    raise ScenarioValidationError(f"{name} contains a null byte")
                if len(content.encode("utf-8")) > self.MAX_SOURCE_BYTES:
                    raise ScenarioValidationError(
                        f"{name} exceeds the {self.MAX_SOURCE_BYTES}-byte limit"
                    )

            with TemporaryDirectory(prefix="scenario-editor-") as staging_name:
                staging = Path(staging_name)
                for name in required:
                    (staging / name).write_text(files[name], encoding="utf-8")

                # Reject an attempted rename before compiling cross-file
                # references so the authoring API reports the protected field.
                if "definition.yaml" in files:
                    try:
                        definition = yaml.safe_load(files["definition.yaml"])
                        submitted_id = definition["scenario"]["id"]
                    except (KeyError, TypeError, yaml.YAMLError):
                        submitted_id = None
                    if submitted_id is not None and submitted_id != scenario_id:
                        raise ScenarioValidationError(
                            "definition.yaml scenario.id must remain "
                            f"{scenario_id}; received {submitted_id}"
                        )
                compiled = self.compiler.compile(staging)

            if compiled.scenario.id != scenario_id:
                raise ScenarioValidationError(
                    f"definition.yaml scenario.id must remain {scenario_id}; "
                    f"received {compiled.scenario.id}"
                )

            originals = {
                name: (directory / name).read_text(encoding="utf-8")
                for name in required
                if (directory / name).is_file()
            }
            try:
                for name in required:
                    self._atomic_write(directory / name, files[name])
                self.load()
            except Exception:
                for name in required:
                    path = directory / name
                    if name in originals:
                        self._atomic_write(path, originals[name])
                    elif path.exists():
                        path.unlink()
                self.load()
                raise
            return self.get(scenario_id)

    def _directory(self, scenario_id: str) -> Path:
        try:
            return self._directories[scenario_id]
        except KeyError as exc:
            raise KeyError(f"scenario not found: {scenario_id}") from exc

    @staticmethod
    def _dump_yaml(value: dict[str, object]) -> str:
        return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary_name: str | None = None
        original = path.stat() if path.exists() else None
        parent = path.parent.stat()
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.chown(
                temporary_name,
                original.st_uid if original else parent.st_uid,
                original.st_gid if original else parent.st_gid,
            )
            os.chmod(
                temporary_name,
                S_IMODE(original.st_mode) if original else 0o644,
            )
            os.replace(temporary_name, path)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
