import json

import httpx
import pytest

from app.domain.scenarios.models import CommunicationStyle, FactDefinition
from app.llm.errors import LLMProviderError
from app.llm.models import ResponseCertainty, RoleResponseRequest
from app.llm.ollama_provider import OllamaLLMProvider


def role_request() -> RoleResponseRequest:
    return RoleResponseRequest(
        role_id="soc",
        role_display_name="SOC Analyst",
        responsibilities=["investigate"],
        communication_style=CommunicationStyle(tone="technical", verbosity="medium"),
        simulation_time=10,
        permitted_facts=[
            FactDefinition(
                id="F001",
                type="observation",
                statement="A failed login was observed.",
                confidence="confirmed",
            )
        ],
        confidence_semantics={"confirmed": "established fact"},
        trainee_question="What happened?",
    )


async def test_ollama_provider_sends_schema_constrained_chat_request():
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "message": "A failed login was observed.",
                            "referenced_fact_ids": ["F001"],
                            "certainty": "confirmed",
                        }
                    ),
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider(
            "http://ollama:11434/",
            "gpt-oss:120b",
            client=client,
        )
        result = await provider.generate_role_response(role_request())

    assert captured["model"] == "gpt-oss:120b"
    assert captured["stream"] is False
    assert captured["format"]["additionalProperties"] is False
    assert captured["messages"][1] == {"role": "user", "content": "What happened?"}
    assert result.certainty == ResponseCertainty.CONFIRMED
    assert result.referenced_fact_ids == ["F001"]


async def test_ollama_provider_rejects_invalid_structured_response():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not JSON"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OllamaLLMProvider(
            "http://ollama:11434",
            "gpt-oss:120b",
            client=client,
        )

        with pytest.raises(
            LLMProviderError,
            match="Ollama returned an invalid structured role response",
        ):
            await provider.generate_role_response(role_request())
