from pathlib import Path

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
