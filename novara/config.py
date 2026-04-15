"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    novara_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://novara:novara@localhost:5432/novara"
    sync_database_url: str = "postgresql+psycopg2://novara:novara@localhost:5432/novara"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # HTTP client
    http_timeout: int = 30
    http_max_connections: int = 20
    http_user_agent: str = "Novara/0.1 (+https://github.com/slothking1/novara007)"

    # Cover storage
    cover_storage_path: str = "/tmp/novara/covers"

    # Ingestion rate limiting
    ingestion_rate_limit: float = 1.0

    @field_validator("log_level")
    @classmethod
    def uppercase_log_level(cls, v: str) -> str:
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
