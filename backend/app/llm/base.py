from collections.abc import AsyncIterator
from typing import Protocol

from .models import RoleResponse, RoleResponseRequest


class LLMProvider(Protocol):
    async def generate_role_response(
        self, request: RoleResponseRequest
    ) -> RoleResponse:
        ...


class StreamingLLMProvider(Protocol):
    def stream_role_response(
        self, request: RoleResponseRequest
    ) -> AsyncIterator[str]:
        """Yield raw structured-response fragments from the provider."""
        ...
