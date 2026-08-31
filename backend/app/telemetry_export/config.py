"""Phase 4.6 -- export configuration (M4-4.6-FR-002, FR-003).

**Two layers, and the per-environment one wins.** The platform default lives in
:class:`~app.core.config.Settings` -- twelve-factor env vars, set once per
deployment, not editable at runtime. A tenant that needs a different
destination per environment (traces from PRODUCTION to Datadog, from STAGING to
a local Grafana) declares it in ``Environment.policy["telemetry_export"]``,
which is the same JSONB document this codebase already uses for every other
governed per-environment setting (allowed models, change windows, budgets).

**The endpoint is a config value, never a code path.** Swapping Datadog for
Grafana for Splunk is editing ``endpoint`` (and possibly ``headers`` for the
vendor's auth). :data:`SUPPORTED_PROTOCOLS` is a closed set of *transports*
(OTLP over HTTP today; the grpc slot is named but not built), never a vendor
list -- vendors consume OTLP, they are not switched between here.

Validation raises :class:`ExportConfigError`, which the route maps to
``EXPORT_CONFIG_INVALID``. A *runtime* export failure is never surfaced this
way -- that is exporter-health state (FR-022), not a config error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core.config import settings

#: Wire transports this platform can speak. Not a vendor list -- Datadog, Azure
#: Monitor, Grafana, Splunk and Elastic all sit behind ``otlp-http``. ``null``
#: is the explicit no-op sink (configured-but-inert), used when export is
#: disabled or a test wants the pipeline without a collector.
SUPPORTED_PROTOCOLS: frozenset[str] = frozenset({"otlp-http", "null"})

#: What to do when the bounded buffer is full (FR-021). ``drop_oldest`` keeps
#: the newest telemetry, which is what an operator watching a live incident
#: wants; ``drop_newest`` keeps the earliest; ``block_bounded`` waits up to a
#: short timeout for room and then drops. Never "grow" -- that option does not
#: exist, which is the §4.6 guarantee.
BUFFER_FULL_POLICIES: frozenset[str] = frozenset(
    {"drop_oldest", "drop_newest", "block_bounded"}
)

_POLICY_KEY = "telemetry_export"


class ExportConfigError(ValueError):
    """An export configuration document is malformed or self-contradictory.

    A ``ValueError`` -- it is caught at the management route and mapped to
    ``EXPORT_CONFIG_INVALID`` (HTTP 422). It must never reach an execution: a
    bad export config disables export, it does not fail an agent."""


@dataclass(frozen=True)
class ExportConfig:
    """The resolved, validated export configuration for one scope.

    Frozen: a configuration describes a destination at a moment. The dispatcher
    reads it once per cycle rather than caching it, so an operator's change
    takes effect on the next cycle without a restart, but a single cycle always
    sees one coherent config."""

    enabled: bool = False
    protocol: str = "otlp-http"
    endpoint: str = ""
    #: Extra HTTP headers for the collector -- this is where a vendor's own auth
    #: goes (``DD-API-KEY``, an Authorization bearer for Grafana Cloud). Carried
    #: opaquely; never logged, never audited, never echoed in a health read.
    headers: dict[str, str] = field(default_factory=dict)
    #: Hard ceiling on buffered spans. Reached only when the collector is down
    #: long enough for the dispatcher to lap it; past it the full-policy runs.
    buffer_max_spans: int = 10_000
    #: Spans per OTLP export request.
    batch_size: int = 512
    #: Per-request network timeout. A slow collector must not hold the
    #: dispatcher thread indefinitely (§36's "slow collector" limb).
    timeout_seconds: float = 5.0
    full_policy: str = "drop_oldest"

    @property
    def active(self) -> bool:
        """True when export should actually attempt to reach a collector."""
        return self.enabled and self.protocol != "null" and bool(self.endpoint)

    @property
    def endpoint_host(self) -> str:
        """scheme://host[:port] -- no path, no query, no userinfo. This is the
        most that goes into an audit record: enough to see *where* telemetry is
        being sent, nothing that could be a credential."""
        if not self.endpoint:
            return ""
        parsed = urlparse(self.endpoint)
        host = f"{parsed.scheme}://{parsed.hostname or ''}"
        if parsed.port:
            host += f":{parsed.port}"
        return host

    def redacted(self) -> dict:
        """The shape a health/config read may return -- header *names* only,
        never their values, and the endpoint host without any userinfo."""
        parsed = urlparse(self.endpoint) if self.endpoint else None
        safe_endpoint = ""
        if parsed is not None:
            safe_endpoint = f"{parsed.scheme}://{parsed.hostname or ''}"
            if parsed.port:
                safe_endpoint += f":{parsed.port}"
            safe_endpoint += parsed.path or ""
        return {
            "enabled": self.enabled,
            "active": self.active,
            "protocol": self.protocol,
            "endpoint": safe_endpoint,
            "header_names": sorted(self.headers),
            "buffer_max_spans": self.buffer_max_spans,
            "batch_size": self.batch_size,
            "timeout_seconds": self.timeout_seconds,
            "full_policy": self.full_policy,
        }


def _platform_defaults() -> ExportConfig:
    return ExportConfig(
        enabled=settings.TELEMETRY_EXPORT_ENABLED,
        protocol=settings.TELEMETRY_EXPORT_PROTOCOL,
        endpoint=settings.TELEMETRY_EXPORT_OTLP_ENDPOINT,
        headers=dict(settings.TELEMETRY_EXPORT_HEADERS or {}),
        buffer_max_spans=settings.TELEMETRY_EXPORT_BUFFER_MAX_SPANS,
        batch_size=settings.TELEMETRY_EXPORT_BATCH_SIZE,
        timeout_seconds=settings.TELEMETRY_EXPORT_TIMEOUT_SECONDS,
        full_policy=settings.TELEMETRY_EXPORT_FULL_POLICY,
    )


def validate_policy_block(block: object) -> dict:
    """Validate a candidate ``Environment.policy["telemetry_export"]`` document.

    Returns the normalized block on success; raises :class:`ExportConfigError`
    otherwise. Only the fields a tenant may set per environment are accepted
    here -- buffer sizing and timeouts stay platform-level, because a tenant
    tuning the buffer down to 1 would turn drop-oldest into "drop everything"
    and call it configuration."""
    if not isinstance(block, dict):
        raise ExportConfigError("telemetry_export must be an object.")

    allowed = {"enabled", "endpoint", "protocol", "headers"}
    unknown = set(block) - allowed
    if unknown:
        raise ExportConfigError(
            f"Unknown telemetry_export keys: {sorted(unknown)}. "
            f"Allowed: {sorted(allowed)}."
        )

    out: dict = {}

    if "enabled" in block:
        if not isinstance(block["enabled"], bool):
            raise ExportConfigError("telemetry_export.enabled must be a boolean.")
        out["enabled"] = block["enabled"]

    protocol = block.get("protocol", "otlp-http")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ExportConfigError(
            f"Unsupported protocol {protocol!r}. Supported: {sorted(SUPPORTED_PROTOCOLS)}. "
            f"A specific vendor (Datadog, Grafana, ...) is not a protocol -- it consumes OTLP."
        )
    out["protocol"] = protocol

    endpoint = block.get("endpoint", "")
    if endpoint:
        if not isinstance(endpoint, str):
            raise ExportConfigError("telemetry_export.endpoint must be a string.")
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ExportConfigError(
                f"telemetry_export.endpoint must be an absolute http(s) URL, got {endpoint!r}."
            )
    out["endpoint"] = endpoint

    headers = block.get("headers", {})
    if not isinstance(headers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
    ):
        raise ExportConfigError("telemetry_export.headers must be a string->string object.")
    _reject_secretish_header_values(headers)
    out["headers"] = headers

    if out.get("enabled") and out["protocol"] != "null" and not out["endpoint"]:
        raise ExportConfigError(
            "telemetry_export is enabled with an OTLP protocol but no endpoint -- "
            "nothing would be exported. Set an endpoint or disable it."
        )
    return out


def _reject_secretish_header_values(headers: dict[str, str]) -> None:
    """A header *value* is opaque and may legitimately be a token, so we do not
    inspect it. But a header whose *name* implies the value is a platform
    secret (our own JWT signing key, a DB URL) is almost certainly a mistake,
    and one we should not carry to a third party."""
    banned = {"jwt-secret", "database-url", "signing-key", "db-password"}
    for name in headers:
        if name.strip().lower().replace("_", "-") in banned:
            raise ExportConfigError(
                f"Refusing a header named {name!r} in an export config -- it names a "
                f"platform secret, not a collector credential."
            )


def resolve_export_config(policy: dict | None) -> ExportConfig:
    """The effective export config for a scope, given its environment policy.

    Platform defaults, then the per-environment ``telemetry_export`` block
    overlaid on top. A block that fails validation is ignored with the platform
    default kept -- resolution happens on the dispatcher thread, and a tenant's
    typo in a policy document must never be able to raise there (§9). The
    management route validates on write, so a stored-but-invalid block means
    someone edited the JSONB directly."""
    base = _platform_defaults()
    block = (policy or {}).get(_POLICY_KEY)
    if not isinstance(block, dict):
        return base
    try:
        clean = validate_policy_block(block)
    except ExportConfigError:
        return base
    return ExportConfig(
        enabled=clean.get("enabled", base.enabled),
        protocol=clean.get("protocol", base.protocol),
        endpoint=clean.get("endpoint", base.endpoint),
        headers={**base.headers, **clean.get("headers", {})},
        buffer_max_spans=base.buffer_max_spans,
        batch_size=base.batch_size,
        timeout_seconds=base.timeout_seconds,
        full_policy=base.full_policy,
    )
