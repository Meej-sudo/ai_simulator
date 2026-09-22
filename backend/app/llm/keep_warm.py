"""Keeps the configured Ollama model loaded while an exercise is in use.

The remote Ollama server unloads a model a few minutes after the last request
it received, which makes the first message of an exercise slow. Starting an
exercise preloads the model, and a periodic heartbeat reloads it whenever
nothing else has reached the server recently. The server's own keep-alive is
never overridden, so the model unloads normally once the app stops asking.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .errors import LLMProviderError
from .ollama_provider import OllamaLLMProvider

logger = logging.getLogger(__name__)

POLL_SECONDS = 30.0
# Ollama's default keep-alive is 5 minutes. Reload after 4 minutes of silence
# so network latency and timing jitter cannot let the model unload first.
RELOAD_AFTER_IDLE_SECONDS = 240.0
# Stop the heartbeat once nothing has used the model for this long, and let
# the server unload it on its own.
SESSION_TTL_SECONDS = 1800.0


class OllamaKeepWarm:
    """Preloads the active Ollama model and keeps it loaded while in use."""

    def __init__(
        self,
        configuration,
        *,
        poll_seconds: float = POLL_SECONDS,
        reload_after_idle_seconds: float = RELOAD_AFTER_IDLE_SECONDS,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
    ):
        self._configuration = configuration
        self._poll_seconds = poll_seconds
        self._reload_after_idle_seconds = reload_after_idle_seconds
        self._session_ttl_seconds = session_ttl_seconds
        self._active_until = 0.0
        self._tasks: set[asyncio.Task] = set()

    def _provider(self) -> OllamaLLMProvider | None:
        """The active provider, or None when Ollama is not the one in use."""
        provider = getattr(self._configuration, "provider", None)
        return provider if isinstance(provider, OllamaLLMProvider) else None

    def touch(self) -> None:
        """Record that an exercise is in use, extending the heartbeat window."""
        self._active_until = time.monotonic() + self._session_ttl_seconds

    def schedule_preload(self) -> None:
        """Start loading the model without blocking the caller."""
        self.touch()
        provider = self._provider()
        if provider is None:
            return
        task = asyncio.create_task(self._load(provider))
        # Hold a reference so the task is not garbage collected mid-flight.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _load(self, provider: OllamaLLMProvider) -> None:
        try:
            await provider.preload()
        except LLMProviderError as exc:
            # A failed load is not fatal: the next request loads the model.
            logger.warning("Ollama preload failed: %s", exc)

    def _due(self, provider: OllamaLLMProvider, now: float) -> bool:
        # A real chat request keeps the exercise alive just as much as an
        # explicit start does, so either can hold the heartbeat open.
        active_until = max(
            self._active_until,
            provider.last_request_at + self._session_ttl_seconds,
        )
        if now >= active_until:
            return False
        return now - provider.last_request_at >= self._reload_after_idle_seconds

    async def _tick(self) -> None:
        provider = self._provider()
        if provider is not None and self._due(provider, time.monotonic()):
            await self._load(provider)

    async def run(self) -> None:
        """Poll until cancelled, reloading the model whenever it falls idle."""
        while True:
            await asyncio.sleep(self._poll_seconds)
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the heartbeat must not die
                logger.exception("Ollama keep-warm tick failed")
