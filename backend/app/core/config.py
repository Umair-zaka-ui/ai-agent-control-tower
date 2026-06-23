"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed application settings.

    Values are read from environment variables and, if present, a local
    ``.env`` file. See ``.env.example`` for the full list of options.
    """

    PROJECT_NAME: str = "AI Agent Control Tower"
    API_PREFIX: str = ""

    # Database
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/agent_control_tower"
    )

    # JWT / Auth
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # CORS. ``NoDecode`` stops pydantic-settings from trying to JSON-parse the
    # env value so our validator can accept a simple comma separated string.
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow CORS origins to be provided as a comma separated string."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


# A single, importable settings instance used across the app.
settings = Settings()
