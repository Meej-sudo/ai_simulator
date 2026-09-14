from typing import Protocol

from .models import RoleResponse, RoleResponseRequest


class LLMProvider(Protocol):
    async def generate_role_response(
        self, request: RoleResponseRequest
    ) -> RoleResponse:
        ...
