from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, env_prefix="", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "siderfold-backend"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://siderfold:siderfold@127.0.0.1:5432/siderfold"
    database_connect_timeout_seconds: int = Field(default=2, ge=1, le=60)
    source_registry_path: Path = Path(__file__).resolve().parents[2] / "config" / "sources.toml"

    @field_validator("database_url")
    @classmethod
    def require_psycopg_postgres_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg scheme")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
