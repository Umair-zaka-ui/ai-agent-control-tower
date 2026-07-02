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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day (legacy login)

    # --- Phase 4.2.1: authentication architecture (token strategy §6/§7) ---
    JWT_ISSUER: str = "ai-agent-control-tower"
    JWT_AUDIENCE: str = "ai-agent-control-tower-api"
    # Short-lived access tokens (SRS §6: 15 minutes) and longer refresh tokens.
    AUTH_ACCESS_TOKEN_TTL_SECONDS: int = 15 * 60
    AUTH_REFRESH_TOKEN_TTL_SECONDS: int = 7 * 24 * 60 * 60

    # CORS. ``NoDecode`` stops pydantic-settings from trying to JSON-parse the
    # env value so our validator can accept a simple comma separated string.
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # --- Phase 2: agent API keys ---
    API_KEY_PREFIX: str = "agt_live_"

    # --- Phase 2: email notifications (SMTP / Mailtrap for development) ---
    NOTIFICATIONS_ENABLED: bool = False
    SMTP_HOST: str = "sandbox.smtp.mailtrap.io"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@control-tower.local"
    SMTP_USE_TLS: bool = True

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
