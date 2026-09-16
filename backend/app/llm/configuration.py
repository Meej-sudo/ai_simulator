from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings

from .base import LLMProvider
from .fake_provider import FakeLLMProvider
from .ollama_provider import OllamaLLMProvider, list_ollama_models
from .unconfigured_provider import UnconfiguredLLMProvider


@dataclass(frozen=True)
class LLMSelection:
    provider: str | None = None
    model: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class LLMConfiguration:
    """Loads, validates, applies, and persists the active LLM selection."""

    available_providers = ("ollama",)

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.llm_settings_path
        self.selection = self._load()
        self.provider = self._build_provider(self.selection)

    @property
    def configured(self) -> bool:
        return not isinstance(self.provider, UnconfiguredLLMProvider)

    def _load(self) -> LLMSelection:
        values = self._read_env_file()
        provider = _clean(values.get("LLM_PROVIDER")) or _clean(
            self.settings.llm_provider
        )

        if provider == "ollama":
            model = _clean(values.get("OLLAMA_MODEL")) or _clean(
                self.settings.ollama_model
            )
        elif provider == "openai":
            model = _clean(values.get("OPENAI_MODEL")) or _clean(
                self.settings.openai_model
            )
        else:
            model = None

        return LLMSelection(provider=provider, model=model)

    def _read_env_file(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}

        values: dict[str, str] = {}
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _build_provider(self, selection: LLMSelection) -> LLMProvider:
        if selection.provider == "fake":
            return FakeLLMProvider()

        if selection.provider == "openai":
            if not self.settings.openai_api_key or not selection.model:
                return UnconfiguredLLMProvider()
            from .openai_provider import OpenAILLMProvider

            return OpenAILLMProvider(self.settings.openai_api_key, selection.model)

        if selection.provider == "ollama" and selection.model:
            return OllamaLLMProvider(
                self.settings.ollama_base_url,
                selection.model,
                self.settings.ollama_timeout_seconds,
            )

        return UnconfiguredLLMProvider()

    async def models(self, provider: str) -> list[str]:
        if provider != "ollama":
            raise ValueError(f"unsupported configurable LLM provider: {provider}")
        return await list_ollama_models(
            self.settings.ollama_base_url,
            self.settings.ollama_discovery_timeout_seconds,
        )

    async def update(self, provider: str, model: str) -> LLMSelection:
        if provider != "ollama":
            raise ValueError(f"unsupported configurable LLM provider: {provider}")

        available_models = await self.models(provider)
        if model not in available_models:
            raise ValueError(f"Ollama model is not available: {model}")

        selection = LLMSelection(provider=provider, model=model)
        self._write(selection)
        self.selection = selection
        self.provider = self._build_provider(selection)
        return selection

    def _write(self, selection: LLMSelection) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "# Managed by the AI Incident Trainer model configuration UI.\n"
            f"LLM_PROVIDER={selection.provider}\n"
            f"OLLAMA_MODEL={selection.model}\n"
        )

        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            # The persisted file contains only provider/model names. Keep it
            # readable from the host even when the container runs as root.
            os.chmod(temporary_name, 0o644)
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
