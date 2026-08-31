"""Phase 4.7 -- SLO definition management (M4-4.7-FR-001, FR-005).

CRUD over ``slo_definitions``, tenant-scoped. Validation raises
:class:`SLODefinitionError`, which the route maps to ``SLO_DEFINITION_INVALID``.

**The objective direction is not a stored field.** ``success_rate`` is always
"higher is better" and ``latency_p95`` is always "lower is better"
(``app.slo.sli.SLI_SPECS``). An operator cannot store a self-contradictory
objective, and evaluation never has to guess which way the comparison runs.

**The error budget is defaulted on create, never absent.** For ``success_rate``
it is ``1 - target``; for the "lower is better" rate SLIs it is ``target``; for
the latency SLIs it is the fraction of samples allowed to exceed the target
(default 0.05). An operator may override it, within sane bounds.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import SLODefinition
from app.slo.sli import SLI_NAMES, SLI_SPECS

SCOPE_TYPES: frozenset[str] = frozenset({"ORGANIZATION", "AGENT", "VERSION", "ENVIRONMENT"})

#: Rolling window spec -> timedelta. A closed set: an SLO window is a small
#: vocabulary, not a free-form duration, so an operator cannot define a "37m14s"
#: window nobody can reason about.
WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

#: Below this many terminal samples in the window, an evaluation is
#: INSUFFICIENT_DATA regardless of how good or bad the few look (M4-4.7-FR-004).
#: A platform constant, not a per-SLO knob -- the discipline is the same for
#: every objective, and 3.5/4.5 both made it a constant too.
MIN_SAMPLES = 20

_DEFAULT_LATENCY_BUDGET_FRACTION = 0.05


class SLODefinitionError(ValueError):
    """An SLO definition is malformed. Mapped to ``SLO_DEFINITION_INVALID``
    (422); it never reaches an execution."""


def default_error_budget(sli: str, target: float) -> float:
    direction, unit = SLI_SPECS[sli]
    if unit == "ms":
        return _DEFAULT_LATENCY_BUDGET_FRACTION
    if direction == "higher_better":       # success_rate
        return round(max(0.0, 1.0 - target), 6)
    return round(max(0.0, target), 6)      # lower-is-better rate: the allowed rate


def validate_definition(payload: dict) -> dict:
    """Validate and normalize a create/update payload. Returns the clean dict."""
    out: dict = {}

    name = str(payload.get("name") or "").strip()
    if not (1 <= len(name) <= 120):
        raise SLODefinitionError("name must be 1-120 characters.")
    out["name"] = name

    sli = payload.get("sli")
    if sli not in SLI_NAMES:
        raise SLODefinitionError(
            f"Unknown sli {sli!r}. Known: {sorted(SLI_NAMES)}.")
    out["sli"] = sli
    direction, unit = SLI_SPECS[sli]

    scope_type = payload.get("scope_type", "ORGANIZATION")
    if scope_type not in SCOPE_TYPES:
        raise SLODefinitionError(
            f"Unknown scope_type {scope_type!r}. Known: {sorted(SCOPE_TYPES)}.")
    scope_id = payload.get("scope_id")
    if scope_type == "ORGANIZATION":
        if scope_id is not None:
            raise SLODefinitionError("scope_id must be null for an ORGANIZATION-scoped SLO.")
    else:
        if scope_id is None:
            raise SLODefinitionError(f"scope_id is required for a {scope_type}-scoped SLO.")
        out["scope_id"] = _as_uuid(scope_id, "scope_id")
    out["scope_type"] = scope_type

    window = payload.get("window", "24h")
    if window not in WINDOWS:
        raise SLODefinitionError(
            f"Unknown window {window!r}. Known: {sorted(WINDOWS)}.")
    out["window"] = window

    try:
        target = float(payload["target"])
    except (KeyError, TypeError, ValueError):
        raise SLODefinitionError("target must be a number.") from None
    if unit == "ratio":
        if not (0.0 < target <= 1.0):
            raise SLODefinitionError(
                f"target for {sli} is a ratio and must be in (0, 1]; got {target}.")
    else:  # ms
        if target <= 0:
            raise SLODefinitionError(
                f"target for {sli} is a latency in milliseconds and must be positive; got {target}.")
    out["target"] = target

    if "error_budget" in payload and payload["error_budget"] is not None:
        try:
            budget = float(payload["error_budget"])
        except (TypeError, ValueError):
            raise SLODefinitionError("error_budget must be a number.") from None
        if not (0.0 < budget <= 1.0):
            raise SLODefinitionError("error_budget must be in (0, 1].")
        out["error_budget"] = round(budget, 6)
    else:
        out["error_budget"] = default_error_budget(sli, target)

    if "enabled" in payload and payload["enabled"] is not None:
        if not isinstance(payload["enabled"], bool):
            raise SLODefinitionError("enabled must be a boolean.")
        out["enabled"] = payload["enabled"]

    return out


def _as_uuid(value, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise SLODefinitionError(f"{field} must be a UUID.") from None


class SLOService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, organization_id: uuid.UUID, *, enabled: bool | None = None,
             sli: str | None = None) -> list[SLODefinition]:
        stmt = select(SLODefinition).where(SLODefinition.organization_id == organization_id)
        if enabled is not None:
            stmt = stmt.where(SLODefinition.enabled.is_(enabled))
        if sli is not None:
            stmt = stmt.where(SLODefinition.sli == sli)
        return list(self.db.execute(stmt.order_by(SLODefinition.name)).scalars())

    def get_or_none(self, organization_id: uuid.UUID,
                    slo_id: uuid.UUID) -> SLODefinition | None:
        row = self.db.get(SLODefinition, slo_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    def create(self, organization_id: uuid.UUID, actor_id: uuid.UUID | None,
               payload: dict) -> SLODefinition:
        clean = validate_definition(payload)
        if self.db.execute(
            select(SLODefinition.id).where(
                SLODefinition.organization_id == organization_id,
                SLODefinition.name == clean["name"])
        ).first() is not None:
            raise SLODefinitionError(f"An SLO named {clean['name']!r} already exists.")
        row = SLODefinition(
            organization_id=organization_id, created_by=actor_id,
            name=clean["name"], sli=clean["sli"], scope_type=clean["scope_type"],
            scope_id=clean.get("scope_id"), target=clean["target"],
            window=clean["window"], error_budget=clean["error_budget"],
            enabled=clean.get("enabled", True),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: SLODefinition, payload: dict) -> SLODefinition:
        # Merge onto the existing row so a partial update validates as a whole.
        merged = {
            "name": payload.get("name", row.name),
            "sli": payload.get("sli", row.sli),
            "scope_type": payload.get("scope_type", row.scope_type),
            "scope_id": payload.get("scope_id", row.scope_id),
            "target": payload.get("target", float(row.target)),
            "window": payload.get("window", row.window),
            "error_budget": payload.get("error_budget", float(row.error_budget)),
            "enabled": payload.get("enabled", row.enabled),
        }
        clean = validate_definition(merged)
        if clean["name"] != row.name and self.db.execute(
            select(SLODefinition.id).where(
                SLODefinition.organization_id == row.organization_id,
                SLODefinition.name == clean["name"])
        ).first() is not None:
            raise SLODefinitionError(f"An SLO named {clean['name']!r} already exists.")
        row.name = clean["name"]
        row.sli = clean["sli"]
        row.scope_type = clean["scope_type"]
        row.scope_id = clean.get("scope_id")
        row.target = clean["target"]
        row.window = clean["window"]
        row.error_budget = clean["error_budget"]
        row.enabled = clean.get("enabled", row.enabled)
        self.db.flush()
        return row

    def delete(self, row: SLODefinition) -> None:
        self.db.delete(row)
        self.db.flush()
