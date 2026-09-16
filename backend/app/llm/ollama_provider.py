import json
from collections.abc import AsyncIterator

import httpx

from .errors import LLMProviderError
from .models import RoleResponse, RoleResponseRequest
from .prompts import build_system_prompt


async def list_ollama_models(
    base_url: str,
    timeout_seconds: float = 30,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    endpoint = f"{base_url.rstrip('/')}/api/tags"
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=timeout_seconds) as request_client:
                response = await request_client.get(endpoint)
        else:
            response = await client.get(endpoint)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise LLMProviderError(
            f"Ollama model discovery timed out after {timeout_seconds:g} seconds"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LLMProviderError(
            f"Ollama model discovery returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise LLMProviderError(
            f"Could not connect to Ollama at {base_url.rstrip('/')}"
        ) from exc

    try:
        models = response.json()["models"]
        names = {
            item.get("name") or item.get("model")
            for item in models
            if isinstance(item, dict)
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMProviderError("Ollama returned an invalid model list") from exc

    return sorted(name for name in names if isinstance(name, str) and name)


class OllamaLLMProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 300,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = client

    def _payload(self, request: RoleResponseRequest, *, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_system_prompt(request)},
                {"role": "user", "content": request.trainee_question},
            ],
            "format": RoleResponse.model_json_schema(),
            "stream": stream,
            "options": {"temperature": 0.2},
        }

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        payload = self._payload(request, stream=False)

        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
            else:
                response = await self.client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Ollama request timed out after {self.timeout_seconds:g} seconds"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc

        try:
            content = response.json()["message"]["content"]
            return RoleResponse.model_validate_json(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                "Ollama returned an invalid structured role response"
            ) from exc

    async def stream_role_response(
        self, request: RoleResponseRequest
    ) -> AsyncIterator[str]:
        payload = self._payload(request, stream=True)

        if self.client is None:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async for fragment in self._stream(client, payload):
                    yield fragment
        else:
            async for fragment in self._stream(self.client, payload):
                yield fragment

    async def _stream(
        self,
        client: httpx.AsyncClient,
        payload: dict,
    ) -> AsyncIterator[str]:
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if event.get("error"):
                            raise LLMProviderError(str(event["error"]))
                        fragment = event.get("message", {}).get("content", "")
                    except (AttributeError, TypeError, ValueError) as exc:
                        raise LLMProviderError(
                            "Ollama returned an invalid streaming response"
                        ) from exc
                    if fragment:
                        yield fragment
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Ollama request timed out after {self.timeout_seconds:g} seconds"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Could not connect to Ollama at {self.base_url}"
            ) from exc
