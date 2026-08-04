"""Phase 2.1.3 SRS ACT-INT-FR-042..047 — ``ConnectorHealthService``.

A health check answers two independent questions, kept structurally
separate:

1. **Reachability** — ``Connector.health_check(configuration)``, the ABC
   method every connector type implements. Receives only the instance's
   own ``configuration`` — never a credential.
2. **Authentication validity** — reuses ``ConnectorCredentialService.
   validate()`` (2.1.2) entirely, rather than duplicating credential
   logic here or handing decrypted secrets to a connector's own code.
   This is a deliberate security property: nothing in this module, and
   nothing in a connector's ``health_check()``, ever sees a decrypted
   credential. Only ``ConnectorCredentialService`` itself does, exactly
   as before.

Overall ``result`` is ``HEALTHY`` only when both are true (or auth is
declared ``NONE``); ``UNHEALTHY`` when either cleanly reports false;
``ERROR`` when either probe raises an unexpected exception — distinct
from ``UNHEALTHY`` because an error means the check itself couldn't
reach a conclusion, not that it concluded "down" (``ACT-INT-FR-042``,
AC-09).

**Alerting (``ACT-INT-FR-046``)**: no new notification channel was
built. This codebase's only existing outbound-notification mechanism
(``app/services/notification_service.py``) is a direct SMTP sender with
no subscription/recipient-list concept to hook a connector-health event
into, and its own existing "alert-worthy" precedent
(``RUNTIME_TOOL_EGRESS_DENIED``, Phase 5.6a.1) is exactly this pattern:
a severity-tagged audit event a human reviews via a dashboard/query, not
a push notification. Every health check emits
``INTEGRATION_CONNECTOR_HEALTH_CHECKED`` (informational); an actual
``active -> failed`` transition rides the *existing*
``INTEGRATION_CONNECTOR_STATE_CHANGED`` event (unchanged from 2.1.1,
`ConnectorService._transition` now tags it ``severity: CRITICAL`` when
``to_state == "failed"``) — that is this codebase's alerting signal for
this sub-phase, not a dedicated new event.

**Bounded retention (``ACT-INT-FR-045``)**: a simple cap-at-N rollup —
after recording a check, rows beyond the ``_HEALTH_HISTORY_RETENTION``
most recent (per instance) are deleted. Not a time-based retention
policy; revisit if per-instance check volume ever grows enough for a
flat cap to matter (the interim scheduler in this sub-phase runs at
most once per ``CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS``, so 200 rows
is weeks of history at any sane interval).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.integration.auth.service import ConnectorCredentialService
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.integration import Connector, ConnectorHealthCheck, ConnectorInstance
from app.models.user import User

_HEALTH_HISTORY_RETENTION = 200
_NO_AUTH_SCHEME = "NONE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_reason(exc: Exception) -> str:
    """Truncated, never assumed to be safe by construction for anything
    beyond this module's own controlled raise sites — but every
    exception that reaches here originates from either a connector's own
    ``health_check()`` (a connector author's responsibility, exactly
    like every other codebase convention that trusts internal code) or
    from ``ConnectorCredentialService``, whose own exceptions were
    already designed in 2.1.2 to never carry credential material."""
    return str(exc)[:500]


class ConnectorHealthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check(
        self, actor: User | None, organization_id: uuid.UUID, connector_instance_id: uuid.UUID,
        *, check_type: str = "ON_DEMAND", transport: Any = None,
    ) -> ConnectorHealthCheck:
        connector_service = ConnectorService(self.db)
        instance = connector_service.get_or_404(organization_id, connector_instance_id)
        type_row = self.db.get(Connector, instance.connector_id)
        implementation = ConnectorTypeService(self.db).implementation_for(type_row)

        started = time.monotonic()
        try:
            reachable, auth_valid, reason = self._probe(
                implementation, instance, type_row, actor, organization_id, transport,
            )
        except Exception as exc:  # noqa: BLE001 -- an unexpected failure is ERROR, not UNHEALTHY
            latency_ms = int((time.monotonic() - started) * 1000)
            return self._record(
                actor, instance, check_type, reachable=False, auth_valid=False,
                result="ERROR", reason=_safe_reason(exc), latency_ms=latency_ms,
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        healthy = reachable and auth_valid
        result = "HEALTHY" if healthy else "UNHEALTHY"
        return self._record(
            actor, instance, check_type, reachable=reachable, auth_valid=auth_valid,
            result=result, reason=None if healthy else reason, latency_ms=latency_ms,
        )

    def _probe(
        self, implementation, instance: ConnectorInstance, type_row: Connector, actor: User | None,
        organization_id: uuid.UUID, transport: Any,
    ) -> tuple[bool, bool, str | None]:
        """Runs both probes; lets any exception propagate to ``check()``'s
        own ``ERROR`` handling — neither probe swallows an unexpected
        failure into a false ``UNHEALTHY``."""
        reachable = implementation.health_check(instance.configuration)

        scheme_id = (type_row.auth_requirements or {}).get("scheme", _NO_AUTH_SCHEME)
        if scheme_id == _NO_AUTH_SCHEME:
            return reachable, True, None if reachable else "connector reported unreachable"

        credential_service = ConnectorCredentialService(self.db)
        if not credential_service.has_credential(organization_id, instance.id, scheme_id):
            return reachable, False, "no credential configured for the declared auth scheme"

        result = credential_service.validate(actor, organization_id, instance.id, scheme_id, transport=transport)
        auth_valid = bool(result["success"])
        if reachable and auth_valid:
            return reachable, auth_valid, None
        if not reachable:
            return reachable, auth_valid, "connector reported unreachable"
        return reachable, auth_valid, str(result["message"])

    def _record(
        self, actor: User | None, instance: ConnectorInstance, check_type: str, *, reachable: bool,
        auth_valid: bool, result: str, reason: str | None, latency_ms: int,
    ) -> ConnectorHealthCheck:
        row = ConnectorHealthCheck(
            connector_instance_id=instance.id, organization_id=instance.organization_id, check_type=check_type,
            reachable=reachable, auth_valid=auth_valid, result=result, reason=reason, latency_ms=latency_ms,
        )
        self.db.add(row)
        instance.last_health_check_at = _now()
        instance.current_health = result
        self.db.flush()

        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.INTEGRATION_CONNECTOR_HEALTH_CHECKED,
            organization_id=instance.organization_id, actor_id=actor.id if actor else None,
            meta={"connector_instance_id": str(instance.id), "check_type": check_type,
                  "reachable": reachable, "auth_valid": auth_valid, "result": result, "reason": reason},
        )

        self._enforce_retention(instance.id, must_keep=row.id)

        healthy = result == "HEALTHY"
        connector_service = ConnectorService(self.db)
        if not healthy and instance.lifecycle_state == "active":
            connector_service.mark_failed(actor, instance.organization_id, instance.id, reason=reason or "health check failed")
        elif healthy and instance.lifecycle_state == "failed":
            connector_service.recover(actor, instance.organization_id, instance.id)
        else:
            self.db.commit()

        self.db.refresh(row)
        return row

    def _enforce_retention(self, connector_instance_id: uuid.UUID, *, must_keep: uuid.UUID) -> None:
        """``must_keep`` guards against the check just recorded ever being
        rolled off by a same-timestamp ordering tie (`checked_at` is
        second-resolution ``server_default=func.now()`` — two rows
        inserted in the same transaction can share a value)."""
        keep_ids = set(self.db.execute(
            select(ConnectorHealthCheck.id).where(ConnectorHealthCheck.connector_instance_id == connector_instance_id)
            .order_by(ConnectorHealthCheck.checked_at.desc()).limit(_HEALTH_HISTORY_RETENTION)
        ).scalars())
        keep_ids.add(must_keep)
        self.db.execute(
            delete(ConnectorHealthCheck).where(
                ConnectorHealthCheck.connector_instance_id == connector_instance_id,
                ConnectorHealthCheck.id.notin_(keep_ids),
            )
        )

    def history(
        self, organization_id: uuid.UUID, connector_instance_id: uuid.UUID, *, limit: int = 50, offset: int = 0,
    ) -> list[ConnectorHealthCheck]:
        ConnectorService(self.db).get_or_404(organization_id, connector_instance_id)  # tenant-scope check
        return list(self.db.execute(
            select(ConnectorHealthCheck).where(
                ConnectorHealthCheck.connector_instance_id == connector_instance_id,
                ConnectorHealthCheck.organization_id == organization_id,
            ).order_by(ConnectorHealthCheck.checked_at.desc()).limit(limit).offset(offset)
        ).scalars())
