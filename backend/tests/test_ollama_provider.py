import json

import httpx
import pytest

from app.domain.scenarios.models import (
    CommunicationStyle,
    HypothesisDefinition,
    ObservationDefinition,
    PersonalityProfile,
    PersonalityTraits,
)
from app.llm.errors import LLMProviderError
from app.llm.models import (
    AssessmentInterpretationRequest,
    EligibleInvestigation,
    InvestigationInterpretationRequest,
    ResponseCertainty,
    RoleResponseRequest,
)
from app.llm.ollama_provider import OllamaLLMProvider, list_ollama_models


def role_request() -> RoleResponseRequest:
    return RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        personality=PersonalityProfile(
            summary="Calm and skeptical.",
            traits=PersonalityTraits(
                openness="high",
                conscientiousness="high",
                extraversion="low",
                agreeableness="medium",
                emotional_stability="high",
            ),
            behavioral_tendencies=["Lead with evidence."],
            under_pressure="Become more methodical.",
        ),
        simulation_time=10,
        permitted_observations=[
            ObservationDefinition(
                id="O001",
                source="identity_monitoring",
                statement="A failed login was observed.",
                reliability="high",
            )
        ],
        permitted_findings=[],
        trainee_question="What happened?",
    )


async def test_ollama_provider_sends_schema_constrained_role_request():
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps({
                "message": "A failed login was observed.",
                "referenced_evidence_ids": ["O001"],
                "certainty": "high",
            })}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider("http://ollama:11434/", "gpt-oss:120b", client=client)
        result = await provider.generate_role_response(role_request())

    assert captured["model"] == "gpt-oss:120b"
    assert captured["stream"] is False
    assert captured["format"]["additionalProperties"] is False
    system_prompt = captured["messages"][0]["content"]
    assert "PERSONALITY" in system_prompt
    assert "Summary: Calm and skeptical." in system_prompt
    assert "- Openness: high" in system_prompt
    assert "Personality affects manner" in system_prompt
    assert captured["messages"][1] == {"role": "user", "content": "What happened?"}
    assert result.certainty == ResponseCertainty.HIGH
    assert result.referenced_evidence_ids == ["O001"]


async def test_ollama_provider_supports_investigation_and_assessment_contracts():
    responses = [
        {"matched": True, "investigation_id": "I004", "reason": "Clear match."},
        {"assessments": [{
            "hypothesis_id": "H002",
            "confidence": "medium",
            "basis_evidence_ids": ["O001"],
        }]},
    ]
    captured: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(responses.pop(0))}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider("http://ollama:11434", "local-model", client=client)
        investigation = await provider.interpret_investigation(
            InvestigationInterpretationRequest(
                trainee_request="Find the outbound destination.",
                performer_role="soc",
                eligible_investigations=[
                    EligibleInvestigation(
                        id="I004",
                        label="Identify outbound destination",
                        request_description="Determine where traffic went.",
                        match_hints=["outbound destination"],
                    )
                ],
            )
        )
        assessment = await provider.interpret_assessment(
            AssessmentInterpretationRequest(
                trainee_statement="Exfiltration is plausible based on O001.",
                actor_role="soc",
                hypotheses=[
                    HypothesisDefinition(
                        id="H002",
                        key="data_exfiltration",
                        label="Data exfiltration",
                    )
                ],
                known_observations=role_request().permitted_observations,
                known_findings=[],
                confidence_semantics={"medium": "plausible"},
            )
        )

    assert investigation.investigation_id == "I004"
    assert assessment.assessments[0].hypothesis_id == "H002"
    prompt_text = json.dumps(captured)
    assert "ground_truth" not in prompt_text
    assert "reveal_findings" not in prompt_text


async def test_ollama_provider_streams_structured_response_fragments():
    captured: dict[str, object] = {}
    structured = json.dumps(
        {
            "message": "**Confirmed:** A failed login was observed.",
            "referenced_evidence_ids": ["O001"],
            "certainty": "confirmed",
        }
    )
    fragments = [structured[:18], structured[18:47], structured[47:]]

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = "\n".join(
            json.dumps({"message": {"role": "assistant", "content": fragment}})
            for fragment in fragments
        )
        return httpx.Response(200, text=f"{body}\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider(
            "http://ollama:11434",
            "qwen3.8-flash-next:latest",
            client=client,
        )
        received = [fragment async for fragment in provider.stream_role_response(role_request())]

    assert captured["stream"] is True
    assert received == fragments
    parsed = json.loads("".join(received))
    assert parsed["message"].startswith("**Confirmed:**")


async def test_ollama_provider_rejects_invalid_structured_response():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not JSON"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider("http://ollama:11434", "local-model", client=client)
        with pytest.raises(LLMProviderError, match="invalid structured role response"):
            await provider.generate_role_response(role_request())


async def test_ollama_model_discovery_returns_sorted_unique_names():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen3.8-flash-next"},
                    {"model": "llama3.2:latest"},
                    {"name": "qwen3.8-flash-next"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        models = await list_ollama_models("http://ollama:11434/", client=client)

    assert models == ["llama3.2:latest", "qwen3.8-flash-next"]


async def test_ollama_model_discovery_reports_connection_failure():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(
            LLMProviderError,
            match="Could not connect to Ollama at http://ollama:11434",
        ):
            await list_ollama_models("http://ollama:11434", client=client)
