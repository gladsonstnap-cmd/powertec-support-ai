from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PowerTec Support AI"
    app_env: str = "development"
    secret_key: str = Field(default="change-me-in-development", min_length=16)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    seed_demo_data: bool = False
    demo_admin_password: str | None = None
    database_url: str = "postgresql+psycopg://powertec:powertec_dev_password@localhost:5432/powertec_support"
    redis_url: str = "redis://localhost:6379/0"
    backend_cors_origins: list[AnyHttpUrl] | str = "http://localhost:3000"
    whatsapp_provider: str = "mock"
    whatsapp_max_media_size_mb: int = 20
    whatsapp_request_timeout_seconds: int = 30
    messaging_simulator_enabled: bool = True
    ai_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str | None = None
    ai_request_timeout_seconds: int = 45
    ai_max_context_messages: int = 30
    ai_max_context_characters: int = 30000
    knowledge_max_file_size_mb: int = 20
    knowledge_chunk_size: int = 1200
    knowledge_chunk_overlap: int = 150
    knowledge_require_approval: bool = True
    ai_orchestrator_enabled: bool = True
    ai_orchestrator_max_steps: int = 12
    ai_orchestrator_max_tool_attempts: int = 2
    ai_orchestrator_failure_threshold: int = 3
    ai_orchestrator_simulation_only: bool = True

    @property
    def cors_origins(self) -> list[str]:
        if isinstance(self.backend_cors_origins, str):
            return [item.strip() for item in self.backend_cors_origins.split(",") if item.strip()]
        return [str(origin) for origin in self.backend_cors_origins]


@lru_cache
def get_settings() -> Settings:
    return Settings()
