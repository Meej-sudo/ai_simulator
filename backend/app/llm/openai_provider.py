from openai import AsyncOpenAI

from .models import RoleResponse, RoleResponseRequest
from .prompts import build_system_prompt


class OpenAILLMProvider:
    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_role_response(self, request: RoleResponseRequest) -> RoleResponse:
        result = await self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": build_system_prompt(request)},
                {"role": "user", "content": request.trainee_question},
            ],
            text_format=RoleResponse,
            store=False,
        )
        if result.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured role response")
        return result.output_parsed
