import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import router
from app.core.database import get_db
from app.llm.errors import LLMProviderError
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.scenario_registry import ScenarioRegistry


SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def test_http_session_workflow_includes_auditable_timestamps(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}")
    Base.metadata.create_all(engine)
    database = Session(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.include_router(router)

    def database_override():
        yield database

    app.dependency_overrides[get_db] = database_override

    with TestClient(app) as client:
        catalog = client.get("/scenarios")
        assert catalog.status_code == 200
        assert catalog.json()[0]["variants"][0]["id"] == "track_alpha"
        assert {
            item["id"] for item in catalog.json()[0]["decision_categories"]
        } == {"containment", "exfiltration", "notification"}

        created = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert client.post(f"/sessions/{session_id}/start").status_code == 200
        assert client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 45}
        ).status_code == 200

        streamed = client.post(
            f"/sessions/{session_id}/ask/stream",
            json={"target_role": "soc", "message": "What happened?"},
        )
        stream_events = [json.loads(line) for line in streamed.text.splitlines()]
        assert streamed.status_code == 200
        assert stream_events[0] == {"type": "start"}
        assert any(event["type"] == "delta" for event in stream_events)
        assert stream_events[-1]["type"] == "complete"
        assert "Based on what I currently know" in "".join(
            event["content"]
            for event in stream_events
            if event["type"] == "delta"
        )

        events = client.get(f"/sessions/{session_id}/events")
        assert events.status_code == 200
        assert all("created_at" in event for event in events.json())

        evaluation = client.get(f"/sessions/{session_id}/evaluation")
        assert evaluation.status_code == 409

        decision = client.post(
            f"/sessions/{session_id}/actions/decision",
            json={
                "actor_role": "ciso",
                "category": "notification",
                "decision": "Brief the executive team.",
                "rationale": "Leadership needs a shared operating picture.",
            },
        )
        assert decision.status_code == 200

        completed = client.post(f"/sessions/{session_id}/complete")
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        evaluation = client.get(f"/sessions/{session_id}/evaluation")
        assert evaluation.status_code == 200
        assert "relevant_events" in evaluation.json()["rules"][0]
        assert client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 5}
        ).status_code == 409
        final_events = client.get(f"/sessions/{session_id}/events").json()
        assert final_events[-1]["event_type"] == "SESSION_COMPLETED"

class FailingLLMProvider:
    async def generate_role_response(self, request):
        raise LLMProviderError("Could not connect to Ollama at http://ollama:11434")


def test_llm_failure_returns_cors_enabled_bad_gateway(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cors.sqlite3'}")
    Base.metadata.create_all(engine)
    database = Session(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.scenarios = registry
    app.state.llm_provider = FailingLLMProvider()
    app.include_router(router)

    def database_override():
        yield database

    app.dependency_overrides[get_db] = database_override

    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        )
        session_id = created.json()["id"]
        client.post(f"/sessions/{session_id}/start")
        response = client.post(
            f"/sessions/{session_id}/ask",
            headers={"Origin": "http://localhost:3000"},
            json={"target_role": "soc", "message": "What happened?"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Could not connect to Ollama at http://ollama:11434"
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


class StubLLMConfiguration:
    available_providers = ("ollama",)

    def __init__(self):
        self.selection = SimpleNamespace(provider=None, model=None)
        self.provider = None
        self.configured = False

    async def models(self, provider: str):
        assert provider == "ollama"
        return ["llama3.2:latest", "qwen3.8-flash-next"]

    async def update(self, provider: str, model: str):
        self.selection = SimpleNamespace(provider=provider, model=model)
        self.provider = FakeLLMProvider()
        self.configured = True


def test_llm_configuration_api_discovers_and_applies_model():
    app = FastAPI()
    app.state.llm_configuration = StubLLMConfiguration()
    app.state.llm_provider = None
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.get("/settings/llm")
        models = client.get("/settings/llm/models", params={"provider": "ollama"})
        updated = client.put(
            "/settings/llm",
            json={"provider": "ollama", "model": "qwen3.8-flash-next"},
        )

    assert initial.status_code == 200
    assert initial.json() == {
        "provider": None,
        "model": None,
        "configured": False,
        "available_providers": ["ollama"],
    }
    assert models.json() == {
        "provider": "ollama",
        "models": ["llama3.2:latest", "qwen3.8-flash-next"],
    }
    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    assert updated.json()["model"] == "qwen3.8-flash-next"
    assert isinstance(app.state.llm_provider, FakeLLMProvider)


def test_session_creation_requires_configured_model(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'unconfigured.sqlite3'}")
    Base.metadata.create_all(engine)
    database = Session(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = FakeLLMProvider()
    app.state.llm_configuration = SimpleNamespace(configured=False)
    app.include_router(router)

    def database_override():
        yield database

    app.dependency_overrides[get_db] = database_override

    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "No AI model is configured. Select a provider and model before "
            "starting an exercise."
        )
    }
