"""Phase 4.6 -- the export management service (M4-4.6-FR-002, §7, §8).

Reads and writes the per-environment export configuration that lives in
``Environment.policy["telemetry_export"]``, and reads the process-local
exporter health. Everything here is tenant-scoped through
:class:`~app.runtime.environment.service.EnvironmentService` -- a cross-tenant
environment id is indistinguishable from one that does not exist.

**A config write is audited; a config read is not; routine export is not.**
Pointing telemetry at a third-party collector sends operational metadata
off-platform, so the endpoint/on-off change is a material act
(``RUNTIME_TELEMETRY_EXPORT_CONFIGURED``). Per-span export is telemetry and is
never audited per span.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.user import User
from app.runtime.environment.service import EnvironmentService
from app.runtime.services import _record_event
from app.telemetry_export.config import (
    ExportConfigError,
    resolve_export_config,
    validate_policy_block,
)
from app.telemetry_export.health import exporter_health

_POLICY_KEY = "telemetry_export"


class TelemetryExportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._environments = EnvironmentService(db)

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    def get_config(self, actor: User, environment_id: uuid.UUID) -> dict:
        env = self._environments.get_or_404(actor, environment_id)
        stored = (env.policy or {}).get(_POLICY_KEY)
        resolved = resolve_export_config(env.policy)
        return {
            "environment_id": str(env.id),
            "environment_name": env.name,
            "stored_block": _redact_block(stored) if isinstance(stored, dict) else None,
            "effective": resolved.redacted(),
        }

    def set_config(self, actor: User, environment_id: uuid.UUID, block: dict) -> dict:
        """Validate ``block`` and store it as the environment's
        ``telemetry_export`` policy. Raises ``EXPORT_CONFIG_INVALID`` on a
        malformed document -- never anything that could reach an execution."""
        env = self._environments.get_or_404(actor, environment_id)
        try:
            clean = validate_policy_block(block)
        except ExportConfigError as exc:
            raise IdentityError(ErrorCode.EXPORT_CONFIG_INVALID, str(exc)) from exc

        new_policy = dict(env.policy or {})
        new_policy[_POLICY_KEY] = clean
        env.policy = new_policy

        resolved = resolve_export_config(new_policy)
        _record_event(
            self.db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_EXPORT_CONFIGURED, actor,
            organization_id=actor.organization_id,
            severity="WARNING" if resolved.active else "INFO",
            meta={
                "environment_id": str(env.id),
                "environment_name": env.name,
                "enabled": clean.get("enabled", False),
                "protocol": clean.get("protocol", "otlp-http"),
                # host only -- never a header value, never a path/query
                "endpoint_host": resolved.endpoint_host,
            },
        )
        self.db.commit()
        self.db.refresh(env)
        return self.get_config(actor, env.id)

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def health(self) -> dict:
        """Process-local exporter health plus the platform-default config.

        Buffer depth is only meaningful in a process that runs the dispatcher
        (a worker with the scheduler enabled); an API process that never
        exports still reports its zeroed health record honestly rather than
        pretending export is flowing."""
        return {
            "exporter": exporter_health.snapshot(),
            "platform_default": resolve_export_config(None).redacted(),
        }


def _redact_block(block: dict) -> dict:
    """A stored block, safe to return: header *names* only, endpoint kept (it is
    not a secret -- the secret, if any, is in a header value)."""
    out = {k: v for k, v in block.items() if k != "headers"}
    out["header_names"] = sorted((block.get("headers") or {}).keys())
    return out
