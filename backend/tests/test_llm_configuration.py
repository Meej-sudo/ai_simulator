from pathlib import Path

from app.core.config import Settings
from app.llm import configuration as configuration_module
from app.llm.configuration import LLMConfiguration
from app.llm.ollama_provider import OllamaLLMProvider
from app.llm.unconfigured_provider import UnconfiguredLLMProvider


def settings(path: Path) -> Settings:
    return Settings(
        _env_file=None,
        llm_provider=None,
        llm_settings_path=path,
        openai_api_key=None,
        openai_model=None,
        ollama_base_url="http://ollama:11434",
        ollama_model=None,
    )


def test_no_saved_model_uses_unconfigured_provider(tmp_path: Path):
    configuration = LLMConfiguration(settings(tmp_path / ".env"))

    assert configuration.selection.provider is None
    assert configuration.selection.model is None
    assert configuration.configured is False
    assert isinstance(configuration.provider, UnconfiguredLLMProvider)


async def test_ollama_selection_is_validated_persisted_and_reloaded(
    tmp_path: Path,
    monkeypatch,
):
    async def available_models(base_url: str, timeout_seconds: float):
        assert base_url == "http://ollama:11434"
        return ["llama3.2:latest", "qwen3.8-flash-next"]

    monkeypatch.setattr(
        configuration_module,
        "list_ollama_models",
        available_models,
    )
    path = tmp_path / "runtime" / ".env"
    configuration = LLMConfiguration(settings(path))

    await configuration.update("ollama", "qwen3.8-flash-next")

    assert configuration.configured is True
    assert isinstance(configuration.provider, OllamaLLMProvider)
    assert configuration.provider.model == "qwen3.8-flash-next"
    assert path.read_text(encoding="utf-8") == (
        "# Managed by the AI Incident Trainer model configuration UI.\n"
        "LLM_PROVIDER=ollama\n"
        "OLLAMA_MODEL=qwen3.8-flash-next\n"
    )
    assert path.stat().st_mode & 0o777 == 0o644

    reloaded = LLMConfiguration(settings(path))
    assert reloaded.selection.provider == "ollama"
    assert reloaded.selection.model == "qwen3.8-flash-next"
    assert reloaded.configured is True


async def test_unavailable_ollama_model_is_not_saved(tmp_path: Path, monkeypatch):
    async def available_models(base_url: str, timeout_seconds: float):
        return ["llama3.2:latest"]

    monkeypatch.setattr(
        configuration_module,
        "list_ollama_models",
        available_models,
    )
    path = tmp_path / ".env"
    configuration = LLMConfiguration(settings(path))

    try:
        await configuration.update("ollama", "missing:latest")
    except ValueError as exc:
        assert str(exc) == "Ollama model is not available: missing:latest"
    else:
        raise AssertionError("unavailable model should be rejected")

    assert not path.exists()
    assert configuration.configured is False
