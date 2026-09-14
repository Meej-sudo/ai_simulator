from pathlib import Path

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError
from app.domain.scenarios.models import CompiledScenario, RuntimeScenario


class ScenarioRegistry:
    def __init__(self, root: str | Path, compiler: ScenarioCompiler | None = None):
        self.root = Path(root)
        self.compiler = compiler or ScenarioCompiler()
        self._scenarios: dict[str, CompiledScenario] = {}

    def load(self) -> None:
        scenarios: dict[str, CompiledScenario] = {}
        if not self.root.is_dir():
            raise ScenarioValidationError(f"scenario root does not exist: {self.root}")
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and (directory / "scenario.yaml").is_file():
                compiled = self.compiler.compile(directory)
                scenario_id = compiled.scenario.id
                if scenario_id in scenarios:
                    raise ScenarioValidationError(f"duplicate scenario ID: {scenario_id}")
                scenarios[scenario_id] = compiled
        self._scenarios = scenarios

    def all(self) -> list[CompiledScenario]:
        return list(self._scenarios.values())

    def get(self, scenario_id: str) -> CompiledScenario:
        try:
            return self._scenarios[scenario_id]
        except KeyError as exc:
            raise KeyError(f"scenario not found: {scenario_id}") from exc

    def materialize(self, scenario_id: str, variant_id: str) -> RuntimeScenario:
        return self.compiler.materialize(self.get(scenario_id), variant_id)
