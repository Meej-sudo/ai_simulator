import httpx

from .errors import LLMProviderError
from .models import RoleResponse, RoleResponseRequest
from .prompts import build_system_prompt


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

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_system_prompt(request)},
                {"role": "user", "content": request.trainee_question},
            ],
            "format": RoleResponse.model_json_schema(),
            "stream": False,
            "options": {"temperature": 0.2},
        }

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
