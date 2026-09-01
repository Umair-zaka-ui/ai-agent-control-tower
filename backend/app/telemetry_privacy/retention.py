"""Phase 4.8 -- retention per telemetry class + a safe expiration sweep
(M4-4.8-FR-030..033, §24).

**Retention is per class, not one global period.** Six classes:

| class                | what expires                              | deletes? |
|----------------------|-------------------------------------------|----------|
| ``trace_content``    | ``trace_content`` rows                    | yes      |
| ``trace_metadata``   | ``runtime_events`` rows                    | yes      |
| ``metrics_aggregate``| ``slo_evaluations`` rows (stored windows) | yes      |
| ``alert_history``    | ``runtime_alerts`` in RESOLVED/SUPPRESSED | yes      |
| ``governance_decision`` | ``runtime_governance_decisions``       | **no**   |
| ``financial_record`` | cost/budget ledgers                        | **no**   |

The last two are **retain-only**: their retention is configurable so a tenant
can *document* a minimum, but the sweep never deletes them -- financial and
governance evidence outlives every detailed payload (§24, M4-4.8-FR-031). Every
deletable class targets a **telemetry** table; the sweep never touches an
execution row, an audit row, or domain truth (M4-4.8-FR-032).

**The sweep is idempotent and bounded** (M4-4.8-FR-033): it deletes in batches,
commits between them, and stops after a fixed number of batches -- a second run
picks up where the first stopped, and neither can hold a lock across a large
purge (§9). It is the interim, 3.8-schedulable op, the same pattern 4.5 / 4.7
built. **No scheduler is built here.**
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.runtime import RuntimeAlert, RuntimeEvent, SLOEvaluation, TraceContent

#: The six telemetry classes (M4-4.8-FR-030). Order is display order.
TELEMETRY_CLASSES: tuple[str, ...] = (
    "trace_content",
    "trace_metadata",
    "metrics_aggregate",
    "alert_history",
    "governance_decision",
    "financial_record",
)

#: Classes the sweep will not delete -- evidence that outlives payloads.
RETAIN_ONLY_CLASSES: frozenset[str] = frozenset({"governance_decision", "financial_record"})

#: Default retention if a tenant configures none. Detailed payloads short,
#: evidence long.
DEFAULT_RETENTION_DAYS: dict[str, int] = {
    "trace_content": 30,
    "trace_metadata": 90,
    "metrics_aggregate": 90,
    "alert_history": 365,
    "governance_decision": 2555,
    "financial_record": 2555,
}

#: The minimum a tenant may configure. A content payload may be kept as briefly
#: as a day; governance/financial evidence may never be set below a year.
RETENTION_FLOORS: dict[str, int] = {
    "trace_content": 1,
    "trace_metadata": 7,
    "metrics_aggregate": 7,
    "alert_history": 30,
    "governance_decision": 365,
    "financial_record": 365,
}

#: Rows per delete statement, and the cap on statements per class per run. The
#: product (50k) bounds one run; a scheduler tick that leaves rows simply
#: removes them on the next tick.
_BATCH = 1000
_MAX_BATCHES = 50


class RetentionPolicyError(ValueError):
    """A retention-policy payload is malformed. Mapped to
    ``RETENTION_POLICY_INVALID`` (422)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ClassSweepResult:
    telemetry_class: str
    retention_days: int
    cutoff: str
    deleted: int = 0
    retain_only: bool = False
    truncated: bool = False  # hit the batch cap; more remain for the next run


@dataclass
class SweepResult:
    organization_id: str
    started_at: str
    classes: list[ClassSweepResult] = field(default_factory=list)

    @property
    def total_deleted(self) -> int:
        return sum(c.deleted for c in self.classes)

    def as_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "started_at": self.started_at,
            "total_deleted": self.total_deleted,
            "classes": [c.__dict__ for c in self.classes],
        }


# --------------------------------------------------------------------------- #
# Management
# --------------------------------------------------------------------------- #
def validate_retention_policy(payload: dict) -> dict:
    telemetry_class = payload.get("telemetry_class")
    if telemetry_class not in TELEMETRY_CLASSES:
        raise RetentionPolicyError(
            f"Unknown telemetry_class {telemetry_class!r}. Known: {list(TELEMETRY_CLASSES)}.")
    try:
        days = int(payload["retention_days"])
    except (KeyError, TypeError, ValueError):
        raise RetentionPolicyError("retention_days must be an integer.") from None
    floor = RETENTION_FLOORS[telemetry_class]
    if days < floor:
        raise RetentionPolicyError(
            f"retention_days for {telemetry_class} may not be below {floor} "
            f"(evidence class)" if telemetry_class in RETAIN_ONLY_CLASSES
            else f"retention_days for {telemetry_class} may not be below {floor}.")
    if days > 36525:
        raise RetentionPolicyError("retention_days may not exceed 36525 (100 years).")
    out = {"telemetry_class": telemetry_class, "retention_days": days}
    if "enabled" in payload and payload["enabled"] is not None:
        if not isinstance(payload["enabled"], bool):
            raise RetentionPolicyError("enabled must be a boolean.")
        out["enabled"] = payload["enabled"]
    return out


class RetentionPolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, organization_id: uuid.UUID) -> list:
        from app.models.runtime import TelemetryRetentionPolicy

        return list(self.db.execute(
            select(TelemetryRetentionPolicy)
            .where(TelemetryRetentionPolicy.organization_id == organization_id)
            .order_by(TelemetryRetentionPolicy.telemetry_class)
        ).scalars())

    def effective(self, organization_id: uuid.UUID) -> dict[str, dict]:
        """The effective retention for every class: the tenant row if set, else
        the platform default. What ``GET .../retention-policies`` surfaces."""
        configured = {p.telemetry_class: p for p in self.list(organization_id)}
        out: dict[str, dict] = {}
        for cls in TELEMETRY_CLASSES:
            row = configured.get(cls)
            out[cls] = {
                "telemetry_class": cls,
                "retention_days": row.retention_days if row else DEFAULT_RETENTION_DAYS[cls],
                "enabled": row.enabled if row else True,
                "source": "policy" if row else "platform-default",
                "floor_days": RETENTION_FLOORS[cls],
                "retain_only": cls in RETAIN_ONLY_CLASSES,
            }
        return out

    def upsert(self, organization_id: uuid.UUID, actor_id: uuid.UUID | None,
               payload: dict):
        from app.models.runtime import TelemetryRetentionPolicy

        clean = validate_retention_policy(payload)
        row = self.db.execute(
            select(TelemetryRetentionPolicy).where(
                TelemetryRetentionPolicy.organization_id == organization_id,
                TelemetryRetentionPolicy.telemetry_class == clean["telemetry_class"],
            )
        ).scalar_one_or_none()
        if row is None:
            row = TelemetryRetentionPolicy(
                organization_id=organization_id, created_by=actor_id,
                telemetry_class=clean["telemetry_class"],
                retention_days=clean["retention_days"],
                enabled=clean.get("enabled", True),
            )
            self.db.add(row)
        else:
            row.retention_days = clean["retention_days"]
            row.enabled = clean.get("enabled", row.enabled)
        self.db.flush()
        return row


# --------------------------------------------------------------------------- #
# The sweep
# --------------------------------------------------------------------------- #
class RetentionSweeper:
    """Idempotent, bounded expiration of expired telemetry for one tenant.

    Never raises on a per-class problem -- one class failing to sweep does not
    block the others, and nothing here can affect an execution."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._policies = RetentionPolicyService(db)

    def run(self, organization_id: uuid.UUID) -> SweepResult:
        effective = self._policies.effective(organization_id)
        result = SweepResult(
            organization_id=str(organization_id), started_at=_now().isoformat())
        for cls in TELEMETRY_CLASSES:
            spec = effective[cls]
            cutoff = _now() - timedelta(days=spec["retention_days"])
            cr = ClassSweepResult(
                telemetry_class=cls, retention_days=spec["retention_days"],
                cutoff=cutoff.isoformat(),
                retain_only=cls in RETAIN_ONLY_CLASSES)
            if spec["enabled"] and cls not in RETAIN_ONLY_CLASSES:
                try:
                    cr.deleted, cr.truncated = self._sweep_class(
                        cls, organization_id, cutoff)
                except Exception:  # pragma: no cover - defensive; sweep is best-effort
                    self.db.rollback()
            result.classes.append(cr)
        return result

    def _sweep_class(self, cls: str, organization_id: uuid.UUID,
                     cutoff: datetime) -> tuple[int, bool]:
        deleted = 0
        for _ in range(_MAX_BATCHES):
            ids = self._expired_ids(cls, organization_id, cutoff)
            if not ids:
                return deleted, False
            deleted += self._delete_ids(cls, ids)
            self.db.commit()
        # Cap hit -- more may remain; the next run continues.
        remaining = bool(self._expired_ids(cls, organization_id, cutoff))
        return deleted, remaining

    def _expired_ids(self, cls: str, organization_id: uuid.UUID,
                     cutoff: datetime) -> list[uuid.UUID]:
        if cls == "trace_content":
            stmt = (select(TraceContent.id)
                    .where(TraceContent.organization_id == organization_id,
                           TraceContent.created_at < cutoff)
                    .limit(_BATCH))
        elif cls == "trace_metadata":
            stmt = (select(RuntimeEvent.id)
                    .where(RuntimeEvent.organization_id == organization_id,
                           RuntimeEvent.created_at < cutoff)
                    .limit(_BATCH))
        elif cls == "metrics_aggregate":
            stmt = (select(SLOEvaluation.id)
                    .where(SLOEvaluation.organization_id == organization_id,
                           SLOEvaluation.evaluated_at < cutoff)
                    .limit(_BATCH))
        elif cls == "alert_history":
            stmt = (select(RuntimeAlert.id)
                    .where(RuntimeAlert.organization_id == organization_id,
                           RuntimeAlert.status.in_(("RESOLVED", "SUPPRESSED")),
                           RuntimeAlert.updated_at < cutoff)
                    .limit(_BATCH))
        else:  # pragma: no cover - retain-only classes never reach here
            return []
        return list(self.db.execute(stmt).scalars())

    def _delete_ids(self, cls: str, ids: list[uuid.UUID]) -> int:
        model = {
            "trace_content": TraceContent,
            "trace_metadata": RuntimeEvent,
            "metrics_aggregate": SLOEvaluation,
            "alert_history": RuntimeAlert,
        }[cls]
        res = self.db.execute(delete(model).where(model.id.in_(ids)))
        return res.rowcount or 0

    # ------------------------------------------------------------------ #
    def counts(self, organization_id: uuid.UUID) -> dict[str, int]:
        """Live row counts per deletable class -- for the docs/AC that assert
        the execution row survives a content purge."""
        out: dict[str, int] = {}
        out["trace_content"] = self.db.execute(
            select(func.count()).select_from(TraceContent)
            .where(TraceContent.organization_id == organization_id)).scalar_one()
        return out
