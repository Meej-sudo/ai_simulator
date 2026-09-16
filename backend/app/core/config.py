from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Incident Trainer"
    database_url: str = "postgresql+psycopg://trainer:trainer@db:5432/trainer"
    scenarios_path: Path = Path(__file__).resolve().parents[3] / "content" / "scenarios"
    llm_provider: str | None = None
    llm_settings_path: Path = (
        Path(__file__).resolve().parents[3] / ".llm-config" / ".env"
    )
    openai_api_key: str | None = None
    openai_model: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str | None = None
    ollama_discovery_timeout_seconds: float = 10
    ollama_timeout_seconds: float = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
