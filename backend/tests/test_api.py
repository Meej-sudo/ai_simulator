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


SCENARIOS = Path(__file__).resolve().parents[2] / "content" / "scenarios"


def make_app(tmp_path: Path, provider=None) -> FastAPI:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}")
    Base.metadata.create_all(engine)
    database = Session(engine)
    registry = ScenarioRegistry(SCENARIOS)
    registry.load()
    app = FastAPI()
    app.state.scenarios = registry
    app.state.llm_provider = provider or FakeLLMProvider()
    app.include_router(router)

    def database_override():
        yield database

    app.dependency_overrides[get_db] = database_override
    return app


def test_http_sprint_one_discovery_workflow_and_leakage_boundaries(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        catalog = client.get("/scenarios")
        assert catalog.status_code == 200
        assert {
            item["id"] for item in catalog.json()[0]["decision_categories"]
        } == {"containment", "exfiltration", "notification"}

        detail = client.get("/scenarios/ransomware_001")
        assert detail.status_code == 200
        assert {item["id"] for item in detail.json()["hypotheses"]} == {
            "H001", "H002", "H003", "H004"
        }
        detail_text = detail.text
        assert "ground_truth" not in detail_text
        assert "investigation_outcomes" not in detail_text
        assert "FD004" not in detail_text

        created = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        )
        assert created.status_code == 201
        assert len(created.json()["scenario_version"]) == 64
        assert "scenario_snapshot" not in created.json()
        session_id = created.json()["id"]
        assert client.post(f"/sessions/{session_id}/start").status_code == 200
        assert client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 45}
        ).status_code == 200

        soc_before = client.get(
            f"/sessions/{session_id}/roles/soc/knowledge"
        ).json()
        assert {item["id"] for item in soc_before["observations"]} == {
            "O001", "O002", "O003", "O004", "O005"
        }
        assert soc_before["findings"] == []

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

        request = client.post(
            f"/sessions/{session_id}/investigations",
            json={
                "requester_role": "ciso",
                "performer_role": "soc",
                "request": "Find where that outbound traffic went.",
            },
        )
        assert request.status_code == 200
        assert request.json()["accepted"] is True
        assert request.json()["investigation"]["due_at"] == 50
        assert "reveal_findings" not in request.text
        assert "FD004" not in request.text

        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 5})
        runs = client.get(f"/sessions/{session_id}/investigations")
        assert runs.status_code == 200
        assert runs.json()[0]["status"] == "completed"
        assert "FD004" not in runs.text

        soc_after = client.get(
            f"/sessions/{session_id}/roles/soc/knowledge"
        ).json()
        dpo_before_share = client.get(
            f"/sessions/{session_id}/roles/dpo/knowledge"
        ).json()
        assert {item["id"] for item in soc_after["findings"]} == {"FD004"}
        assert dpo_before_share["findings"] == []

        events = client.get(f"/sessions/{session_id}/events")
        assert events.status_code == 200
        finding_events = [
            event for event in events.json()
            if event["event_type"] == "FINDING_REVEALED"
        ]
        assert finding_events[0]["payload"] == {"redacted": True}
        assert "FD004" not in events.text

        assessment = client.post(
            f"/sessions/{session_id}/assessments",
            json={
                "actor_role": "soc",
                "statement": "Data exfiltration is highly likely based on FD004.",
            },
        )
        assert assessment.status_code == 200
        assert assessment.json()["recorded"][0]["hypothesis_id"] == "H002"
        assert "correct" not in assessment.text.casefold()

        shared = client.post(
            f"/sessions/{session_id}/actions/share-evidence",
            json={
                "from_role": "soc",
                "to_role": "dpo",
                "evidence_id": "FD004",
            },
        )
        assert shared.status_code == 200
        assert {
            item["id"]
            for item in client.get(
                f"/sessions/{session_id}/roles/dpo/knowledge"
            ).json()["findings"]
        } == {"FD004"}

        projection = client.get(f"/sessions/{session_id}/assessments")
        assert projection.status_code == 200
        assert len(projection.json()["history"]) == 1
        assert len(projection.json()["current"]) == 1

        assert client.get(f"/sessions/{session_id}/evaluation").status_code == 409
        completed = client.post(f"/sessions/{session_id}/complete")
        assert completed.json()["status"] == "completed"
        assert client.get(f"/sessions/{session_id}/evaluation").status_code == 200
        assert client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 5}
        ).status_code == 409


class FailingLLMProvider:
    async def generate_role_response(self, request):
        raise LLMProviderError("Could not connect to Ollama at http://ollama:11434")


def test_llm_failure_returns_cors_enabled_bad_gateway(tmp_path: Path):
    app = make_app(tmp_path, FailingLLMProvider())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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



def test_bridge_message_endpoint_supports_external_trainee(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        )
        session_id = created.json()["id"]
        client.post(f"/sessions/{session_id}/start")
        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 10})

        posted = client.post(
            f"/sessions/{session_id}/threads/channel%3Abridge/messages",
            json={
                "text": "Use this observation in the coordinated response.",
                "cited_evidence_ids": ["O001"],
            },
        )

        assert posted.status_code == 200
        events = client.get(f"/sessions/{session_id}/events").json()
        message = next(
            event for event in events if event["event_type"] == "MESSAGE_POSTED"
        )
        assert message["actor_role"] is None
        assert message["payload"]["thread_id"] == "channel:bridge"
        for role in client.get(f"/sessions/{session_id}/roles").json():
            knowledge = client.get(
                f"/sessions/{session_id}/roles/{role['id']}/knowledge"
            ).json()
            assert "O001" in {
                item["id"]
                for item in [*knowledge["observations"], *knowledge["findings"]]
            }


def test_sessions_can_be_listed(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/sessions").json() == []
        created = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()
        listed = client.get("/sessions")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [created["id"]]
        assert listed.json()[0]["status"] == "created"


def test_session_completes_automatically_at_the_time_limit(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")
        advanced = client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 180}
        )
        assert advanced.status_code == 200
        assert advanced.json()["status"] == "completed"
        assert advanced.json()["simulation_time"] == 180
        # Evaluation unlocks immediately after the time limit completes it.
        assert client.get(f"/sessions/{session_id}/evaluation").status_code == 200
        # Completing again is idempotent.
        assert client.post(f"/sessions/{session_id}/complete").status_code == 200
        # Advancing a completed session is rejected.
        assert (
            client.post(
                f"/sessions/{session_id}/advance-time", json={"minutes": 5}
            ).status_code
            == 409
        )


def test_advance_time_clamps_to_the_scenario_duration(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")
        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 170})
        # An advance that would overshoot the duration clamps to the limit
        # instead of erroring, and completes the session.
        advanced = client.post(
            f"/sessions/{session_id}/advance-time", json={"minutes": 15}
        )
        assert advanced.status_code == 200
        assert advanced.json()["simulation_time"] == 180
        assert advanced.json()["status"] == "completed"


def test_investigation_rejection_explains_performer_mismatch(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")
        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 10})
        rejected = client.post(
            f"/sessions/{session_id}/investigations",
            json={
                "requester_role": "soc",
                "performer_role": "ceo",
                "request": "Determine where the login source ip came from",
            },
        )
        assert rejected.status_code == 200
        body = rejected.json()
        assert body["accepted"] is False
        assert "cannot perform any investigation" in body["reason"]
        assert body["suggestions"] == []


def test_investigation_rejection_lists_eligible_suggestions(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")
        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 10})
        rejected = client.post(
            f"/sessions/{session_id}/investigations",
            json={
                "requester_role": "soc",
                "performer_role": "soc",
                "request": "zzzz unrelated gibberish qqqq",
            },
        )
        body = rejected.json()
        assert body["accepted"] is False
        assert {item["id"] for item in body["suggestions"]} >= {"I001", "I002"}


def test_confirmed_assessment_without_confirming_evidence_warns(tmp_path: Path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")
        client.post(f"/sessions/{session_id}/advance-time", json={"minutes": 45})
        response = client.post(
            f"/sessions/{session_id}/assessments",
            json={
                "actor_role": "soc",
                "statement": "Data exfiltration is confirmed based on O004.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["recorded"][0]["confidence"] == "confirmed"
        assert len(body["warnings"]) == 1
        assert "confirmed" in body["warnings"][0]
