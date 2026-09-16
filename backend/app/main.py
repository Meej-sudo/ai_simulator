from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import engine
from app.llm.configuration import LLMConfiguration
from app.models.database import Base
from app.services.scenario_registry import ScenarioRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    registry = ScenarioRegistry(settings.scenarios_path)
    llm_configuration = LLMConfiguration(settings)
    registry.load()
    Base.metadata.create_all(bind=engine)
    app.state.scenarios = registry
    app.state.llm_configuration = llm_configuration
    app.state.llm_provider = llm_configuration.provider
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
