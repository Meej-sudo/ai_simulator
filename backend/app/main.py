from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import engine
from app.llm.fake_provider import FakeLLMProvider
from app.models.database import Base
from app.services.scenario_registry import ScenarioRegistry


def build_llm_provider(settings):
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        from app.llm.openai_provider import OpenAILLMProvider

        return OpenAILLMProvider(settings.openai_api_key, settings.openai_model)
    if settings.llm_provider == "ollama":
        from app.llm.ollama_provider import OllamaLLMProvider

        return OllamaLLMProvider(
            settings.ollama_base_url,
            settings.ollama_model,
            settings.ollama_timeout_seconds,
        )
    raise RuntimeError(f"unsupported LLM_PROVIDER: {settings.llm_provider}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    registry = ScenarioRegistry(settings.scenarios_path)
    registry.load()
    Base.metadata.create_all(bind=engine)
    app.state.scenarios = registry
    app.state.llm_provider = build_llm_provider(settings)
    yield


app = FastAPI(title="AI Incident Trainer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
