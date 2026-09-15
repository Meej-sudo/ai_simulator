import os
from pathlib import Path
from stat import S_IMODE
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import RLock

import yaml

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError
from app.domain.scenarios.models import CompiledScenario, RuntimeScenario


class ScenarioRegistry:
    MAX_SOURCE_BYTES = 512_000

    def __init__(self, root: str | Path, compiler: ScenarioCompiler | None = None):
        self.root = Path(root)
        self.compiler = compiler or ScenarioCompiler()
        self._scenarios: dict[str, CompiledScenario] = {}
        self._directories: dict[str, Path] = {}
        self._lock = RLock()

    def load(self) -> None:
        with self._lock:
            scenarios: dict[str, CompiledScenario] = {}
            directories: dict[str, Path] = {}
            if not self.root.is_dir():
                raise ScenarioValidationError(f"scenario root does not exist: {self.root}")
            for directory in sorted(self.root.iterdir()):
                if directory.is_dir() and (directory / "scenario.yaml").is_file():
                    compiled = self.compiler.compile(directory)
                    scenario_id = compiled.scenario.id
                    if scenario_id in scenarios:
                        raise ScenarioValidationError(f"duplicate scenario ID: {scenario_id}")
                    scenarios[scenario_id] = compiled
                    directories[scenario_id] = directory
            self._scenarios = scenarios
            self._directories = directories

    def all(self) -> list[CompiledScenario]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> CompiledScenario:
        try:
            return self._scenarios[scenario_id]
        except KeyError as exc:
            raise KeyError(f"scenario not found: {scenario_id}") from exc

    def materialize(self, scenario_id: str, variant_id: str) -> RuntimeScenario:
        return self.compiler.materialize(self.get(scenario_id), variant_id)

    def source_files(self, scenario_id: str) -> dict[str, str]:
        with self._lock:
            directory = self._directory(scenario_id)
            return {
                name: (directory / name).read_text(encoding="utf-8")
                for name in self.compiler.REQUIRED_FILES
            }

    def update_document(
        self, scenario_id: str, document: CompiledScenario
    ) -> CompiledScenario:
        files = {
            "scenario.yaml": self._dump_yaml(
                {"scenario": document.scenario.model_dump(mode="json", exclude_none=True)}
            ),
            "roles.yaml": self._dump_yaml(
                {
                    "roles": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.roles
                    ]
                }
            ),
            "external_entities.yaml": self._dump_yaml(
                {
                    "external_entities": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.external_entities
                    ]
                }
            ),
            "evidence.yaml": self._dump_yaml(
                {
                    "observations": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.observations
                    ],
                    "findings": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.findings
                    ],
                }
            ),
            "hypotheses.yaml": self._dump_yaml(
                {
                    "hypotheses": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.hypotheses
                    ]
                }
            ),
            "investigations.yaml": self._dump_yaml(
                {
                    "investigations": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.investigations
                    ]
                }
            ),
            "timeline.yaml": self._dump_yaml(
                {
                    "events": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.timeline
                    ]
                }
            ),
            "variants.yaml": self._dump_yaml(
                {
                    "variants": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.variants
                    ]
                }
            ),
            "scoring.yaml": self._dump_yaml(
                {
                    "rules": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in document.scoring_rules
                    ]
                }
            ),
        }
        return self.update_source_files(scenario_id, files)

    def update_source_files(
        self, scenario_id: str, files: dict[str, str]
    ) -> CompiledScenario:
        with self._lock:
            directory = self._directory(scenario_id)
            required = set(self.compiler.REQUIRED_FILES)
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
                for name in self.compiler.REQUIRED_FILES:
                    (staging / name).write_text(files[name], encoding="utf-8")
                compiled = self.compiler.compile(staging)

            if compiled.scenario.id != scenario_id:
                raise ScenarioValidationError(
                    f"scenario.yaml id must remain {scenario_id}; "
                    f"received {compiled.scenario.id}"
                )

            originals = self.source_files(scenario_id)
            try:
                for name in self.compiler.REQUIRED_FILES:
                    self._atomic_write(directory / name, files[name])
                self.load()
            except Exception:
                for name, content in originals.items():
                    self._atomic_write(directory / name, content)
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
        original = path.stat()
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
            os.chown(temporary_name, original.st_uid, original.st_gid)
            os.chmod(temporary_name, S_IMODE(original.st_mode))
            os.replace(temporary_name, path)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
