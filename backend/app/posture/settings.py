"""Phase 5.5 (M5.5) - ``PostureRuleSettingService``: per-organization
enable / disable / parameter override for a code-defined posture rule.

The rules themselves are code (``app.posture.rules.RULES``) with a versioned
``POSTURE_RULESET_VERSION`` and per-rule ``version``. This table is the
*tenant override* layer: an operator can disable a rule or move a threshold
without a code change, and every change carries a monotonic ``revision`` and
is audited - so a posture score is reconstructable and *why it moved* is
answerable (SRS §12). Absent row = the rule's coded defaults.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.posture import PostureRuleSetting
from app.posture.rules import RULES_BY_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostureRuleSettingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def effective(self, organization_id: uuid.UUID) -> dict[str, dict]:
        """rule_id -> {"enabled", "params", "revision"} - coded defaults with
        any tenant override applied."""
        rows = {
            r.rule_id: r
            for r in self.db.execute(
                select(PostureRuleSetting).where(
                    PostureRuleSetting.organization_id == organization_id
                )
            ).scalars()
        }
        out: dict[str, dict] = {}
        for rule_id, rule in RULES_BY_ID.items():
            row = rows.get(rule_id)
            if row is None:
                out[rule_id] = {"enabled": True, "params": {}, "revision": 0}
            else:
                out[rule_id] = {
                    "enabled": bool(row.enabled),
                    "params": dict(row.params or {}),
                    "revision": int(row.revision),
                }
        return out

    def describe(self, organization_id: uuid.UUID) -> list[dict]:
        eff = self.effective(organization_id)
        return [
            {
                "rule_id": rule.id,
                "control_id": rule.control_id,
                "default_severity": rule.severity,
                "shadow_class": rule.shadow_class,
                "rule_version": rule.version,
                "summary": rule.summary,
                "default_params": rule.default_params,
                "enabled": eff[rule.id]["enabled"],
                "effective_params": {**rule.default_params, **eff[rule.id]["params"]},
                "settings_revision": eff[rule.id]["revision"],
            }
            for rule in RULES_BY_ID.values()
        ]

    def update(self, actor, rule_id: str, *, enabled: bool | None = None,
               params: dict | None = None) -> PostureRuleSetting:
        if rule_id not in RULES_BY_ID:
            raise IdentityError(ErrorCode.POSTURE_RULE_UNKNOWN, f"No such posture rule: {rule_id}.")
        org = actor.organization_id
        row = self.db.execute(
            select(PostureRuleSetting).where(
                PostureRuleSetting.organization_id == org,
                PostureRuleSetting.rule_id == rule_id,
            )
        ).scalars().first()
        prev = None
        if row is None:
            row = PostureRuleSetting(
                organization_id=org, rule_id=rule_id,
                enabled=True if enabled is None else enabled,
                params=params or {}, revision=1, updated_by=actor.id,
            )
            self.db.add(row)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                row = self.db.execute(
                    select(PostureRuleSetting).where(
                        PostureRuleSetting.organization_id == org,
                        PostureRuleSetting.rule_id == rule_id,
                    )
                ).scalars().one()
                prev = {"enabled": row.enabled, "params": dict(row.params or {})}
        else:
            prev = {"enabled": row.enabled, "params": dict(row.params or {})}

        if enabled is not None:
            row.enabled = enabled
        if params is not None:
            row.params = params
        if prev is not None:
            row.revision = int(row.revision) + 1
            row.updated_by = actor.id
            row.updated_at = _now()

        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.POSTURE_RULE_SETTING_CHANGED,
            organization_id=org, actor_id=actor.id,
            meta={"rule_id": rule_id, "previous": prev,
                  "new": {"enabled": row.enabled, "params": dict(row.params or {})},
                  "revision": row.revision},
        )
        self.db.commit()
        self.db.refresh(row)
        return row


__all__ = ["PostureRuleSettingService"]
