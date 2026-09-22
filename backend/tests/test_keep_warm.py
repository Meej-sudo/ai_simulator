import json

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import make_app

from app.llm.errors import LLMProviderError
from app.llm.fake_provider import FakeLLMProvider
from app.llm.keep_warm import OllamaKeepWarm
from app.llm.ollama_provider import CHAT_OPTIONS, OllamaLLMProvider


class Configuration:
    """Stands in for LLMConfiguration, whose provider can change at runtime."""

    def __init__(self, provider):
        self.provider = provider


def provider_with(handler) -> OllamaLLMProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaLLMProvider("http://ollama:11434", "llama3.2", client=client)


async def test_preload_loads_the_model_without_generating_anything():
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"model": "llama3.2", "done": True})

    provider = provider_with(handle)
    await provider.preload()

    body = json.loads(captured["body"])
    assert captured["url"] == "http://ollama:11434/api/generate"
    assert body == {"model": "llama3.2", "options": dict(CHAT_OPTIONS)}
    # A prompt would generate text, and keep_alive would override the server's
    # own unload timer, which this deployment deliberately leaves alone.
    assert "prompt" not in body
    assert "keep_alive" not in body


async def test_preload_uses_the_same_options_as_chat_requests():
    payload = OllamaLLMProvider("http://ollama:11434", "llama3.2")._payload(
        "system",
        "user",
        type("Schema", (), {"model_json_schema": staticmethod(lambda: {})}),
        stream=False,
    )
    assert payload["options"] == dict(CHAT_OPTIONS)


async def test_preload_reports_provider_failures():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(LLMProviderError):
        await provider_with(handle).preload()


async def test_requests_record_when_ollama_was_last_reached():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True})

    provider = provider_with(handle)
    assert provider.last_request_at == 0.0
    await provider.preload()
    assert provider.last_request_at > 0.0


async def test_heartbeat_reloads_only_while_active_and_idle():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True})

    provider = provider_with(handle)
    keeper = OllamaKeepWarm(
        Configuration(provider),
        reload_after_idle_seconds=240,
        session_ttl_seconds=1800,
    )

    now = 10_000.0
    # Nothing has started an exercise yet.
    assert keeper._due(provider, now) is False

    keeper.touch()
    provider.last_request_at = now
    # A request has just been sent, so the model is still loaded.
    assert keeper._due(provider, now + 60) is False
    # Four minutes of silence: reload before the server's timer expires.
    assert keeper._due(provider, now + 241) is True
    # Long after the exercise stopped being used, let the model unload.
    assert keeper._due(provider, now + 4000) is False


async def test_heartbeat_stays_open_while_chat_requests_keep_arriving():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True})

    provider = provider_with(handle)
    keeper = OllamaKeepWarm(Configuration(provider))

    now = 10_000.0
    # Never touched, but a chat request arrived recently: still an active
    # exercise, so the heartbeat keeps the model loaded.
    provider.last_request_at = now
    assert keeper._due(provider, now + 300) is True


async def test_keep_warm_does_nothing_for_other_providers():
    keeper = OllamaKeepWarm(Configuration(FakeLLMProvider()))
    assert keeper._provider() is None
    # Must not raise, start tasks, or reach the network.
    keeper.schedule_preload()
    await keeper._tick()


def test_starting_an_exercise_preloads_the_model(tmp_path):
    """The start endpoint must trigger a preload without waiting for it."""

    class SpyKeepWarm:
        def __init__(self):
            self.preloads = 0

        def schedule_preload(self):
            self.preloads += 1

    app = make_app(tmp_path)
    keeper = SpyKeepWarm()
    app.state.keep_warm = keeper

    with TestClient(app) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        assert keeper.preloads == 0

        started = client.post(f"/sessions/{session_id}/start")
        assert started.status_code == 200
        assert keeper.preloads == 1


def test_starting_an_exercise_works_without_a_keep_warm_service(tmp_path):
    """Deployments that switch keep-warm off must still start exercises."""
    app = make_app(tmp_path)
    assert not hasattr(app.state, "keep_warm")

    with TestClient(app) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        assert client.post(f"/sessions/{session_id}/start").status_code == 200
