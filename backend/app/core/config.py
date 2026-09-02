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

    # --- Phase 4.2.2.3.5: HTTP hardening (integration §15, §16, §23) ----------
    # Security response headers applied to *every* response (§16). Disable only
    # if a reverse proxy already injects them, to avoid duplicate headers.
    SECURITY_HEADERS_ENABLED: bool = True
    # Content-Security-Policy. The API serves JSON, not HTML, so a strict
    # default-deny policy is safe; the SPA is served separately by Vite/CDN.
    SECURITY_CSP: str = "default-src 'none'; frame-ancestors 'none'"
    SECURITY_REFERRER_POLICY: str = "no-referrer"
    SECURITY_PERMISSIONS_POLICY: str = "geolocation=(), microphone=(), camera=()"
    # HSTS is only meaningful over TLS; off by default for local http on :8002.
    # Enable in production (behind HTTPS) to pin the browser to TLS.
    SECURITY_HSTS_ENABLED: bool = False
    SECURITY_HSTS_MAX_AGE: int = 31536000  # 1 year
    # Request correlation (§15): the header carrying a request id in and out. When a
    # caller does not send one, the middleware generates a UUID4 so every log line,
    # audit event and error body can be tied together.
    REQUEST_ID_HEADER: str = "X-Request-ID"
    # Standard success envelope (§5): wrap 2xx JSON responses under /api as
    # ``{"success": true, "data": <payload>, "meta": {request_id, timestamp}}``.
    # Errors are always enveloped by the identity handler regardless of this flag.
    # Off in the test suite (see conftest) so unit/API tests assert the inner
    # resource contract directly; on everywhere else. The SPA unwraps it centrally.
    RESPONSE_ENVELOPE_ENABLED: bool = True

    # --- Phase 4.3.2: Enterprise Permission Engine (§10, §25, §27) ------------
    # Cache resolved permission grants per identity, versioned per org. A role /
    # permission / assignment change bumps the org version and invalidates all rows.
    PERMISSION_CACHE_ENABLED: bool = True
    PERMISSION_CACHE_TTL_SECONDS: int = 300
    # Persist every ALLOW decision from the gate path? Off by default so the
    # <5ms middleware budget is not spent on a DB write per request; DENY is always
    # recorded, and the /authorization/check endpoint always records.
    AUTHZ_LOG_ALLOW_DECISIONS: bool = False

    # --- Phase 2: agent API keys ---
    API_KEY_PREFIX: str = "agt_live_"

    # --- Phase 5.2.4: cryptographic signing, provenance & attestation --------
    # LOCAL is the only implementation today; Azure Key Vault comes at
    # deployment (ACT-VER-NFR-002's closure condition — see
    # docs/runtime/versioning.md's Known Deviations). Swapping is meant to be
    # a config change here, not a rewrite — see
    # app/runtime/versioning/signing/registry.py.
    SIGNING_PROVIDER: str = "LOCAL"
    # Gitignored; local dev/pre-production only. A keypair is auto-generated
    # here on first use if absent (see signing/local.py).
    SIGNING_KEY_PATH: str = "./.keys/"
    SIGNING_DEFAULT_KEY_ID: str = "default"

    # --- Phase 5.7a.1: model provider abstraction (ACT-MDL-FR-001..010) -------
    # The provider identifier used when a version's model_configuration omits
    # one — matches ModelGatewayService's pre-abstraction default exactly.
    MODEL_DEFAULT_PROVIDER: str = "MOCK"
    # Per-provider base URL (ACT-MDL-FR-010) — lets one adapter class serve
    # multiple compatible endpoints (e.g. OpenAI itself vs. a self-hosted
    # OpenAI-compatible gateway) without a code change, just a different
    # registered identifier pointing at the same class with a different URL.
    # MOCK has nothing to call, but still reads this end-to-end so the
    # mechanism is proven before any real provider depends on it.
    MODEL_PROVIDER_BASE_URLS: dict[str, str] = {}

    # --- Phase 5.7a.2: OpenAI-compatible provider adapter (ACT-MDL-FR-020..028) -
    # Per-provider default model name, read by a provider's constructor when
    # a version's model_configuration doesn't carry one through (mirrors
    # MODEL_PROVIDER_BASE_URLS's per-identifier shape).
    MODEL_PROVIDER_DEFAULT_MODELS: dict[str, str] = {}
    # A hanging provider call must not hang the worker indefinitely. No
    # retry/backoff here -- that classification is Phase 5.7a.4.
    MODEL_PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 5.0
    MODEL_PROVIDER_READ_TIMEOUT_SECONDS: float = 30.0
    # Plain configured value, read as-is. Phase 5.7a.5 layered per-organization
    # encrypted credential storage in front of this: an org's own stored
    # credential is tried first; this dict is now only the fallback used when
    # no org-specific credential is configured (see ProviderCredentialService
    # .resolve() in services.py) -- kept, not removed, since it is still the
    # simplest thing that works for a single shared dev/local-only key.
    MODEL_PROVIDER_API_KEYS: dict[str, str] = {}

    # --- Phase 5.7a.3: streaming & token accounting (ACT-MDL-FR-040..049,
    # FR-084..089) -----------------------------------------------------------
    # ACT-MDL-FR-049 -- a streamed call that never finishes must not run
    # forever; ModelGatewayService._invoke_streaming breaks the loop once
    # this budget is exceeded and persists whatever was received so far as
    # an interrupted (not failed) execution. Independent of the existing
    # per-execution DEFAULT_TIMEOUT_SECONDS (ExecutionWorkerService), which
    # still bounds the whole attempt including this.
    MODEL_STREAM_MAX_DURATION_SECONDS: float = 120.0

    # --- Phase 5.7a.4: error taxonomy & resilience (ACT-MDL-FR-060..069) -----
    # Retry only ever applies to the same provider, for a transient
    # classification (RATE_LIMITED/PROVIDER_UNAVAILABLE/TIMEOUT) -- see
    # ModelGatewayService in services.py. 3 total attempts by default
    # (the original call plus up to this many retries).
    MODEL_PROVIDER_MAX_RETRIES: int = 3
    # Backoff is "equal jitter": delay = half + uniform(0, half), where
    # half = min(MAX_DELAY, BASE_DELAY * 2**attempt) / 2 -- deterministically
    # increasing across attempts (until capped) with randomized jitter on
    # top, so a backoff test can assert ordering without a fixed seed.
    MODEL_PROVIDER_RETRY_BASE_DELAY_SECONDS: float = 0.5
    MODEL_PROVIDER_RETRY_MAX_DELAY_SECONDS: float = 8.0
    # Circuit breaker (ACT-MDL-FR-067): per provider identifier, in-process,
    # not persisted across a restart -- a fresh process starts closed. See
    # docs/runtime/providers.md's "known limitation" for why (Milestone 3's
    # distributed worker model is what would need a shared store).
    MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD: int = 5
    MODEL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS: float = 30.0

    # --- Phase 5.7a.5: per-organization provider credentials (ACT-MDL-FR-080..083) ---
    # Plain configured value read as a base64 urlsafe Fernet key, if set. Never
    # hardcoded, never committed -- if unset, one is auto-generated and persisted
    # locally (dev convenience only; see credential_crypto.py's Known Deviation).
    MODEL_CREDENTIAL_ENCRYPTION_KEY: str | None = None
    MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH: str = "./.keys/model_credentials.key"

    # --- Phase M4.11: key-material recovery & fail-loud integrity ------------
    # The encryption-key provider seam (mirrors SIGNING_PROVIDER). LOCAL is the
    # recovery-safe default; a KMS/Vault adapter attaches here — see
    # app/security/encryption_provider.py and docs/security/key-management.md.
    ENCRYPTION_KEY_PROVIDER: str = "LOCAL"
    # Previously-active encryption keys retained so historical ciphertext still
    # decrypts during/after a rotation (newest-first). A rotation = prepend the
    # new key as MODEL_CREDENTIAL_ENCRYPTION_KEY and move the old one here.
    MODEL_CREDENTIAL_ENCRYPTION_KEYS: list[str] = []
    # Fail loud (refuse to serve) when an established install is missing or
    # holding the wrong encryption/signing key, instead of silently
    # regenerating. Only ever set false in a throwaway environment.
    KEY_MATERIAL_FAIL_LOUD: bool = True
    # Allow the startup check to deliberately bootstrap fresh key material when
    # (and only when) the database has NO encrypted state at all. Off by
    # default: a genuine new install bootstraps via `python -m app.security.keys
    # bootstrap` or by setting MODEL_CREDENTIAL_ENCRYPTION_KEY explicitly.
    ENCRYPTION_KEY_ALLOW_BOOTSTRAP: bool = False

    # --- Phase 5.6a.2: tool schema validation & resilience (ACT-TLX-FR-020..029) ---
    # Mirrors MODEL_PROVIDER_MAX_RETRIES/RETRY_*/CIRCUIT_* exactly -- the same
    # "equal jitter" backoff formula and three-state circuit breaker Phase
    # 5.7a.4 built for model calls, reused via services.py's neutral
    # `_backoff_delay`/`_circuit_is_open` core, parameterized by these
    # tool-specific settings instead of the MODEL_PROVIDER_* ones. Only ever
    # applies to a tool call classified as idempotent (ACT-TLX-FR-026);
    # undeclared idempotency means these settings are never consulted at all.
    TOOL_MAX_RETRIES: int = 3
    TOOL_RETRY_BASE_DELAY_SECONDS: float = 0.5
    TOOL_RETRY_MAX_DELAY_SECONDS: float = 8.0
    # Circuit breaker: per tool identifier, in-process, not persisted across
    # a restart -- same known limitation as MODEL_PROVIDER_CIRCUIT_* (see
    # docs/runtime/providers.md).
    TOOL_CIRCUIT_FAILURE_THRESHOLD: int = 5
    TOOL_CIRCUIT_COOLDOWN_SECONDS: float = 30.0
    # ACT-TLX-FR-029 -- a ceiling `ToolGatewayService._invoke_http` enforces
    # per execution id; today's strictly-sequential tool_calls loop never
    # actually contends it (5.6a.3's model-driven loop is what will), but
    # the enforcement point exists now so that loop needs no new mechanism.
    TOOL_MAX_CONCURRENT_REQUESTS_PER_EXECUTION: int = 4

    # --- Phase 5.6a.3: model-driven tool invocation loop (ACT-TLX-FR-041..043) ---
    # Four independent termination conditions (ToolLoopOrchestrator) -- any
    # one ends the loop; a model that keeps retrying an always-failing tool
    # (recoverable since 5.6a.2) must still terminate in bounded time and
    # bounded token spend. Overridable per-deployment via
    # `runtime_limits.maximum_loop_iterations`, mirroring the existing
    # `maximum_retries`/`maximum_execution_seconds` override pattern.
    TOOL_LOOP_MAX_ITERATIONS: int = 10
    TOOL_LOOP_MAX_TOTAL_TOKENS: int = 50_000
    TOOL_LOOP_MAX_WALL_CLOCK_SECONDS: float = 120.0

    # --- Phase 2.1.3: interim in-process connector health scheduler ---
    # Deliberately off by default -- everywhere, including every test run
    # (REPO_STATE §10.2: no distributed scheduler exists yet; Milestone 3
    # owns building one). On-demand checks are the deterministic path
    # this codebase actually relies on; this is a convenience a real
    # deployment opts into explicitly. See app/integration/scheduler.py.
    CONNECTOR_HEALTH_SCHEDULER_ENABLED: bool = False
    CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS: float = 300.0

    # --- Phase 3.9: distributed execution worker fleet (ACT-SRS-M3 §Phase-3.9)
    # How many executions one worker process runs at once (M3-3.9-FR-003).
    # Defaults to 1 rather than to a core count: an execution here is bounded
    # by model and tool network latency, not by CPU, so the right number
    # depends on provider rate limits and is an operational decision. A
    # default that guessed high would silently multiply a tenant's concurrent
    # provider calls the first time anyone started a worker.
    WORKER_CONCURRENCY: int = 1
    # The rolling unit a worker declares itself part of. One cohort by
    # default, which makes an unconfigured fleet roll in a single step -- the
    # honest description of converting an undivided fleet, rather than a
    # pretend multi-step rollout over cohorts that do not exist.
    WORKER_COHORT: str = "default"
    WORKER_POLL_INTERVAL_SECONDS: float = 2.0
    # Silence longer than this means the process is gone (M3-3.9-FR-004).
    # Comfortably more than several poll intervals: a worker busy running a
    # slow execution still heartbeats from its loop, but a briefly overloaded
    # machine should not have its whole fleet declared dead. Independent of
    # execution lease expiry, which recovers the *work* -- see
    # WorkerFleetService.reap_stale_workers for why those two clocks are
    # deliberately separate.
    WORKER_STALE_AFTER_SECONDS: float = 90.0

    # --- Phase 4.4: cost governance & budgets (ACT-SRS-M4 §4.4, §11) ---
    # How much a HARD_LIMIT/APPROVAL_REQUIRED budget holds for an execution
    # when the budget itself names no `reservation_estimate`.
    #
    # The value is a trade, and neither direction is free: hold too much and a
    # tight budget admits fewer concurrent executions than it could afford;
    # hold too little and more executions are in flight than the remaining
    # balance can cover if they all overrun their hold. It is small on purpose
    # -- a default that guessed high would make every unconfigured budget
    # behave as if it were much smaller than its owner wrote down, which is the
    # surprising direction. Owners who need a conservative hold set it per
    # budget, where the knowledge of what their executions cost actually lives.
    BUDGET_DEFAULT_RESERVATION: float = 0.05

    # --- Phase 4.6: OpenTelemetry & metrics interoperability (ACT-SRS-M4 §4.6) ---
    # The platform default export configuration. A tenant may override
    # `enabled`/`endpoint`/`protocol`/`headers` per environment in
    # `Environment.policy["telemetry_export"]`; buffer sizing and timeouts stay
    # platform-level (a tenant tuning the buffer to 1 would turn drop-oldest
    # into "drop everything" and call it configuration).
    #
    # OFF by default, everywhere, including every test run -- the same
    # conservative default 4.1 used for content capture, and the same opt-in
    # posture as CONNECTOR_HEALTH_SCHEDULER_ENABLED. An unconfigured platform
    # exports nothing and runs no background dispatcher thread.
    TELEMETRY_EXPORT_ENABLED: bool = False
    # `otlp-http` (real) or `null` (configured-but-inert). Never a vendor name:
    # Datadog / Azure Monitor / Grafana / Splunk / Elastic all consume OTLP.
    TELEMETRY_EXPORT_PROTOCOL: str = "otlp-http"
    # The OTLP/HTTP collector endpoint, e.g. http://otel-collector:4318/v1/traces.
    TELEMETRY_EXPORT_OTLP_ENDPOINT: str = ""
    # Extra collector headers -- where a vendor's own auth token goes. Carried
    # opaquely; never logged, audited, or echoed in a health read.
    TELEMETRY_EXPORT_HEADERS: dict[str, str] = {}
    # Bounded buffer (M4-4.6-FR-021): a hard ceiling on buffered spans. Reached
    # only when the collector is down long enough for the dispatcher to lap it;
    # past it the full-policy runs. Never unbounded -- that option does not exist.
    TELEMETRY_EXPORT_BUFFER_MAX_SPANS: int = 10_000
    TELEMETRY_EXPORT_BATCH_SIZE: int = 512
    TELEMETRY_EXPORT_TIMEOUT_SECONDS: float = 5.0
    # drop_oldest | drop_newest | block_bounded. `drop_oldest` keeps the newest
    # telemetry, which is what an operator watching a live incident wants.
    TELEMETRY_EXPORT_FULL_POLICY: str = "drop_oldest"
    # The background dispatcher that reads terminal executions, assembles their
    # traces and exports them. Opt-in, like the connector-health scheduler: the
    # API process does not grow a thread just by starting. Drive it a cycle at
    # a time from a test or a worker via ExportDispatcher.run_once().
    TELEMETRY_EXPORT_SCHEDULER_ENABLED: bool = False
    TELEMETRY_EXPORT_SCHEDULER_INTERVAL_SECONDS: float = 30.0
    # How far back a freshly-started dispatcher looks for terminal executions.
    # Bounded so a restart exports the recent past, not the entire backlog.
    TELEMETRY_EXPORT_SCHEDULER_LOOKBACK_SECONDS: float = 300.0

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
