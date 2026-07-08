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
    # MFA step-up challenge token: proves the primary factor only, very short
    # lived. Concrete factor verification lands in a later subpart (SRS §24).
    AUTH_MFA_CHALLENGE_TTL_SECONDS: int = 5 * 60
    # Account lockout (SRS 4.2.2.1 §10): N failures within the window locks the
    # account for the remainder of the window.
    AUTH_LOCKOUT_THRESHOLD: int = 5
    AUTH_LOCKOUT_WINDOW_SECONDS: int = 15 * 60

    # --- Phase 4.2.2.2: session lifecycle (SRS §11, §12) ------------------
    # Idle timeout: no request for this long → session becomes IDLE, then
    # unusable. Absolute timeout: hard ceiling regardless of activity.
    SESSION_IDLE_TIMEOUT_SECONDS: int = 30 * 60  # 30 minutes
    SESSION_ABSOLUTE_TIMEOUT_SECONDS: int = 12 * 60 * 60  # 12 hours
    # "Remember me" extends the ABSOLUTE ceiling only; idle timeout still applies.
    SESSION_REMEMBER_ME_SECONDS: int = 7 * 24 * 60 * 60  # 7 days
    # Warn the client this long before idle expiry so it can prompt the user.
    SESSION_IDLE_WARNING_SECONDS: int = 5 * 60
    # Max concurrent active sessions per user; oldest is revoked past the limit.
    SESSION_MAX_CONCURRENT: int = 5
    # ``last_activity_at`` is only written when this much time has elapsed since
    # the last write, so a burst of requests does not cause a write per request.
    SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS: int = 60
    # Security scoring (SRS §15).
    SESSION_SCORE_NEW_DEVICE_PENALTY: int = 20
    SESSION_SCORE_NEW_COUNTRY_PENALTY: int = 20
    SESSION_SCORE_TOKEN_REUSE_PENALTY: int = 80

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
