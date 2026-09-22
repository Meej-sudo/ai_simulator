"""The trainee must see a role reply while it is still being generated."""

import json

import httpx

from fastapi.testclient import TestClient

from app.llm.models import ResponseCertainty, RoleResponse
from app.llm.ollama_provider import OllamaLLMProvider
from app.llm.validation import (
    SAFE_ROLE_FALLBACK,
    ConstrainedRoleResponder,
    partial_message,
)
from test_api import make_app
from test_ollama_provider import role_request


def test_partial_message_decodes_what_has_arrived_so_far():
    assert partial_message('{"message": "Hello wor') == "Hello wor"
    assert partial_message('{"message": "Line one.\\nLine') == "Line one.\nLine"
    assert partial_message('{"message": "done", "certainty": "low"}') == "done"
    # Nothing usable yet: the key, the colon, or the opening quote is missing.
    assert partial_message('{"mess') == ""
    assert partial_message('{"message"') == ""
    assert partial_message("") == ""


def test_partial_message_stops_at_an_incomplete_escape():
    # A lone backslash may become \\n or \\u2019 once the next fragment lands,
    # so it must not be released as a literal backslash.
    assert partial_message('{"message": "tail\\') == "tail"
    assert partial_message('{"message": "tail\\u20') == "tail"
    assert partial_message('{"message": "tail\\u2019') == "tail’"


def streaming_provider(fragments: list[str]):
    class Provider:
        async def generate_role_response(self, request):  # pragma: no cover
            raise AssertionError("the streaming path must be used")

        async def stream_role_response(self, request):
            for fragment in fragments:
                yield fragment

    return Provider()


def response_json(message: str, evidence: list[str] | None = None) -> str:
    return json.dumps(
        {
            "message": message,
            "referenced_evidence_ids": evidence or [],
            "certainty": "high",
        }
    )


async def test_prose_is_released_before_the_response_is_complete():
    document = response_json("Encryption is spreading.", ["O001"])
    # Split into small fragments the way a provider streams tokens.
    fragments = [document[i : i + 8] for i in range(0, len(document), 8)]

    deltas: list[str] = []
    request = role_request()
    validated = await ConstrainedRoleResponder(
        streaming_provider(fragments)
    ).generate_streamed(request, deltas.append)

    assert validated.response.message == "Encryption is spreading."
    # More than one delta means text reached the caller mid-generation.
    assert len(deltas) > 1
    assert "".join(deltas) == "Encryption is spreading."


async def test_released_text_never_runs_ahead_of_the_decoded_message():
    document = response_json("One. Two. Three.")
    fragments = [document[i : i + 3] for i in range(0, len(document), 3)]

    seen: list[str] = []
    await ConstrainedRoleResponder(streaming_provider(fragments)).generate_streamed(
        role_request(), seen.append
    )

    # Every prefix of the joined deltas is a prefix of the final message, so
    # the UI never shows characters it has to take back.
    joined = ""
    for delta in seen:
        joined += delta
        assert "One. Two. Three.".startswith(joined)


async def test_internal_evidence_ids_are_not_released_to_the_trainee():
    leaked = response_json("The finding FD004 proves exfiltration.", ["FD004"])
    fragments = [leaked[i : i + 6] for i in range(0, len(leaked), 6)]

    deltas: list[str] = []
    validated = await ConstrainedRoleResponder(
        streaming_provider(fragments)
    ).generate_streamed(role_request(), deltas.append)

    # The reply is rejected and the retry produces the same leak, so the safe
    # fallback is returned and no internal ID was ever released.
    assert "FD004" not in "".join(deltas)
    assert validated.violations


async def test_non_streaming_providers_still_report_one_delta():
    class Provider:
        async def generate_role_response(self, request):
            return RoleResponse(
                message="No stream here.",
                referenced_evidence_ids=[],
                certainty=ResponseCertainty.HIGH,
            )

    deltas: list[str] = []
    validated = await ConstrainedRoleResponder(Provider()).generate_streamed(
        role_request(), deltas.append
    )
    assert deltas == ["No stream here."]
    assert validated.response.message == "No stream here."


def test_stream_endpoint_replaces_text_that_was_withheld(tmp_path):
    """A withheld reply must replace what streamed in, not append to it."""

    class LeakingProvider:
        """Always names an internal evidence ID, so both attempts are rejected."""

        async def generate_role_response(self, request):  # pragma: no cover
            raise AssertionError("the streaming path must be used")

        async def stream_role_response(self, request):
            document = response_json("Start of a reply. FD004 confirms it.", ["FD004"])
            for index in range(0, len(document), 6):
                yield document[index : index + 6]

    with TestClient(make_app(tmp_path, provider=LeakingProvider())) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")

        streamed = client.post(
            f"/sessions/{session_id}/ask/stream",
            json={"target_role": "soc", "message": "What happened?"},
        )
        events = [json.loads(line) for line in streamed.text.splitlines()]

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    replacements = [e for e in events if e["type"] == "replace"]

    assert events[0] == {"type": "start"}
    assert events[-1]["type"] == "complete"
    # The leak was never released, and the safe reply replaces the partial text.
    assert "FD004" not in deltas
    assert len(replacements) == 1
    assert replacements[0]["content"] == SAFE_ROLE_FALLBACK.message


def test_stream_endpoint_does_not_replace_a_clean_reply(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        session_id = client.post(
            "/sessions",
            json={"scenario_id": "ransomware_001", "variant_id": "track_alpha"},
        ).json()["id"]
        client.post(f"/sessions/{session_id}/start")

        streamed = client.post(
            f"/sessions/{session_id}/ask/stream",
            json={"target_role": "soc", "message": "What happened?"},
        )
        events = [json.loads(line) for line in streamed.text.splitlines()]

    assert [event for event in events if event["type"] == "replace"] == []
    assert events[-1]["type"] == "complete"


async def test_ollama_streaming_reaches_the_caller_fragment_by_fragment():
    document = response_json("Two sentences here. And a second one.")
    lines = [
        json.dumps({"message": {"content": document[i : i + 5]}}) + "\n"
        for i in range(0, len(document), 5)
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="".join(lines))

    provider = OllamaLLMProvider(
        "http://ollama:11434",
        "llama3.2",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )

    deltas: list[str] = []
    validated = await ConstrainedRoleResponder(provider).generate_streamed(
        role_request(), deltas.append
    )
    assert validated.response.message == "Two sentences here. And a second one."
    assert len(deltas) > 1
