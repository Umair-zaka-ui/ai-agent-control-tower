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

    # --- Phase 4.2.2.3.1: registration, invitations & rate limiting ---------
    # Public URL the invitation / verification links point at.
    APP_BASE_URL: str = "http://localhost:5173"
    INVITATION_TTL_SECONDS: int = 7 * 24 * 60 * 60        # 7 days  (§9)
    EMAIL_VERIFICATION_TTL_SECONDS: int = 24 * 60 * 60    # 24 hours (§12)
    # Rate limiting for public endpoints (§19): 5 requests / minute / IP.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_REQUESTS: int = 5
    RATE_LIMIT_DEFAULT_WINDOW_SECONDS: int = 60
    # Honour X-Forwarded-For only behind a proxy you control. Trusting it
    # unconditionally lets any caller spoof their rate-limit bucket via a header.
    TRUST_PROXY_HEADERS: bool = False
    # Rows of globally-stale rate-limit history reaped per request. Bounded work, so a
    # caller rotating IP addresses cannot leave the table growing for ever.
    RATE_LIMIT_SWEEP_BATCH: int = 50

    # --- Phase 4.2.2.3.4: account protection & risk-based authentication ------
    ACCOUNT_PROTECTION_ENABLED: bool = True
    # Progressive lockout durations, in seconds, by consecutive lock count (§8):
    # 15m, 30m, 1h, 24h. A 5th lock escalates to SECURITY_REVIEW_REQUIRED.
    PROTECTION_LOCKOUT_DURATIONS: tuple[int, ...] = (900, 1800, 3600, 86400)
    PROTECTION_FAILED_THRESHOLD: int = 5           # failures within the window → lock
    PROTECTION_LOCKOUT_WINDOW_SECONDS: int = 15 * 60
    # Brute-force / credential-stuffing thresholds (§9), within the window.
    PROTECTION_BRUTEFORCE_IP_THRESHOLD: int = 20   # failures from one IP
    PROTECTION_STUFFING_DISTINCT_ACCOUNTS: int = 5 # distinct accounts one IP failed
    # Impossible-travel window (§13): different country within this time → risk.
    PROTECTION_IMPOSSIBLE_TRAVEL_SECONDS: int = 2 * 60 * 60
    # Risk-score thresholds → decision (§14). Kept as settings so a deployment can
    # tune posture without a code change.
    PROTECTION_RISK_CHALLENGE_AT: int = 51         # HIGH  → challenge
    PROTECTION_RISK_LOCK_AT: int = 76              # CRITICAL → lock / MFA
    PROTECTION_RISK_BLOCK_AT: int = 91             # SEVERE → block + review
    # CAPTCHA triggers (§28). Placeholder abstraction; no live provider yet.
    PROTECTION_CAPTCHA_ENABLED: bool = False
    PROTECTION_CAPTCHA_FAILED_ATTEMPTS: int = 3
    PROTECTION_CAPTCHA_RISK_AT: int = 50

    # --- Phase 4.2.2.3.3: password reset, account recovery & email change -----
    # Password-reset tokens are short-lived (§8): 30 minutes.
    PASSWORD_RESET_TTL_SECONDS: int = 30 * 60
    # Kill-switch for the whole forgot-password flow (§25 PASSWORD_RESET_DISABLED).
    PASSWORD_RESET_ENABLED: bool = True
    # Email-change verification token lifetime (§8): 24 hours, like activation.
    EMAIL_CHANGE_TTL_SECONDS: int = 24 * 60 * 60
    # A successful reset revokes every session (§13). "Remembered devices" too.
    PASSWORD_RESET_REVOKES_SESSIONS: bool = True

    # --- Phase 4.2.2.3.2: enterprise password policy & credential management ---
    # Password history: reject reuse of the last N hashes (SRS §6, §10).
    PASSWORD_HISTORY_DEPTH: int = 10
    # Expiration (SRS §6, §11). 0 disables expiry.
    PASSWORD_MAX_AGE_DAYS: int = 90
    # Minimum age: a password cannot be changed again within this window, so a user
    # cannot cycle through history to return to a favourite password (SRS §6).
    PASSWORD_MIN_AGE_HOURS: int = 24
    # Days-before-expiry at which the client should start warning the user (§11).
    PASSWORD_EXPIRY_WARNING_DAYS: tuple[int, ...] = (14, 7, 3, 1)
    # Temporary (admin-issued) passwords expire this soon and force a change (§12).
    TEMP_PASSWORD_TTL_HOURS: int = 24
    # Changing a password revokes the user's other sessions by default (SRS §15).
    PASSWORD_CHANGE_REVOKES_SESSIONS: bool = True

    # Where suppressed emails are written when NOTIFICATIONS_ENABLED=false.
    #
    # An onboarding email carries the ONLY copy of a single-use token -- the database
    # stores nothing but its SHA-256. Logging the subject and discarding the body meant
    # every invitation created in dev was permanently unacceptable. The outbox makes the
    # link recoverable. It contains plaintext tokens, so it is written *only* when mail
    # sending is off, and is git-ignored.
    EMAIL_DEV_OUTBOX_PATH: str = "var/dev-outbox.log"

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
