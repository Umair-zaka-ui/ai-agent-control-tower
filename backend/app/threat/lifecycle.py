"""Phase 5.6 (M5.6) - ``ThreatFindingService``: the finding lifecycle.

Identical shape to ``app.posture.lifecycle.PostureFindingService`` (which
itself mirrors ``app.slo.alerts.AlertService``) — the 4.7 create-or-reopen
primitive + operator transitions, applied to ``ThreatFinding``. See that
module's docstring for the full reasoning; it is not repeated here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.threat import ThreatFinding
from app.slo.states import ACTIVE_ALERT_STATUSES, ALLOWED_TRANSITIONS, AlertStatus, max_severity

_MAX_RAISE_ATTEMPTS = 4

_TRANSITION_EVENT = {
    "ACKNOWLEDGED": AuthorizationAuditEvent.THREAT_FINDING_ACKNOWLEDGED,
    "RESOLVED": AuthorizationAuditEvent.THREAT_FINDING_RESOLVED,
    "SUPPRESSED": AuthorizationAuditEvent.THREAT_FINDING_SUPPRESSED,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ThreatFindingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _audit(self, event: AuthorizationAuditEvent, organization_id: uuid.UUID,
               actor_id: uuid.UUID | None, *, meta: dict) -> None:
        AuthorizationAuditService(self.db).record_change(
            event, organization_id=organization_id, actor_id=actor_id, meta=meta
        )

    def get_or_404(self, actor, finding_id: uuid.UUID) -> ThreatFinding:
        f = self.db.get(ThreatFinding, finding_id)
        if f is None or f.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.THREAT_FINDING_NOT_FOUND, "Threat finding not found.")
        return f

    def raise_finding(
        self, *, organization_id: uuid.UUID, rule_id: str, rule_version: str,
        ruleset_version: str, severity: str, agent_id: uuid.UUID, reason: str,
        evidence: dict, attribution: dict, dedup_key: str,
    ) -> ThreatFinding:
        for _ in range(_MAX_RAISE_ATTEMPTS):
            existing = self.db.execute(
                select(ThreatFinding).where(
                    ThreatFinding.organization_id == organization_id,
                    ThreatFinding.dedup_key == dedup_key,
                ).order_by(ThreatFinding.first_seen_at.desc())
            ).scalars().first()

            if existing is not None and existing.status == AlertStatus.SUPPRESSED.value:
                return existing

            if existing is not None and existing.status in ACTIVE_ALERT_STATUSES:
                existing.recurrence_count += 1
                existing.last_seen_at = _now()
                existing.severity = max_severity(existing.severity, severity)
                existing.reason = reason
                existing.evidence = evidence
                existing.attribution = attribution
                existing.rule_version = rule_version
                existing.ruleset_version = ruleset_version
                existing.updated_at = _now()
                self.db.commit()
                self.db.refresh(existing)
                return existing

            if existing is not None and existing.status == AlertStatus.RESOLVED.value:
                reopen_severity = max_severity(existing.severity, severity)
                updated = self.db.execute(
                    update(ThreatFinding)
                    .where(ThreatFinding.id == existing.id, ThreatFinding.status == "RESOLVED")
                    .values(
                        status="OPEN", resolved_at=None, resolved_by=None,
                        acknowledged_at=None, acknowledged_by=None,
                        last_seen_at=_now(), updated_at=_now(),
                        recurrence_count=ThreatFinding.recurrence_count + 1,
                        severity=reopen_severity, reason=reason, evidence=evidence,
                        attribution=attribution, rule_version=rule_version,
                        ruleset_version=ruleset_version,
                    )
                ).rowcount
                if updated == 1:
                    self._audit(AuthorizationAuditEvent.THREAT_FINDING_REOPENED, organization_id, None,
                                meta={"finding_id": str(existing.id), "rule_id": rule_id,
                                      "dedup_key": dedup_key, "severity": reopen_severity})
                    self.db.commit()
                    self.db.refresh(existing)
                    return existing
                self.db.rollback()
                continue

            finding = ThreatFinding(
                organization_id=organization_id, rule_id=rule_id, rule_version=rule_version,
                ruleset_version=ruleset_version, outcome="FINDING", severity=severity,
                status=AlertStatus.OPEN.value, agent_id=agent_id, reason=reason,
                attribution=attribution, evidence=evidence, dedup_key=dedup_key,
                recurrence_count=1, first_seen_at=_now(), last_seen_at=_now(),
            )
            self.db.add(finding)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                continue
            self._audit(AuthorizationAuditEvent.THREAT_FINDING_OPENED, organization_id, None,
                        meta={"finding_id": str(finding.id), "rule_id": rule_id,
                              "dedup_key": dedup_key, "severity": severity, "agent_id": str(agent_id)})
            self.db.commit()
            self.db.refresh(finding)
            return finding

        raise RuntimeError("could not raise threat finding after retries")  # pragma: no cover

    def auto_resolve(self, organization_id: uuid.UUID, dedup_key: str, reason: str) -> ThreatFinding | None:
        finding = self.db.execute(
            select(ThreatFinding).where(
                ThreatFinding.organization_id == organization_id,
                ThreatFinding.dedup_key == dedup_key,
                ThreatFinding.status.in_(tuple(ACTIVE_ALERT_STATUSES)),
            )
        ).scalars().first()
        if finding is None:
            return None
        finding.status = AlertStatus.RESOLVED.value
        finding.resolved_at = _now()
        finding.resolved_by = None
        finding.updated_at = _now()
        finding.evidence = {**(finding.evidence or {}), "auto_resolved": reason}
        self._audit(AuthorizationAuditEvent.THREAT_FINDING_RESOLVED, organization_id, None,
                    meta={"finding_id": str(finding.id), "auto": True, "reason": reason})
        self.db.commit()
        self.db.refresh(finding)
        return finding

    def transition(self, finding: ThreatFinding, target: str, actor_id: uuid.UUID,
                   *, note: str | None = None) -> ThreatFinding:
        current = finding.status
        if current == target:
            return finding
        if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise IdentityError(
                ErrorCode.THREAT_FINDING_TRANSITION_INVALID,
                f"Cannot move a threat finding from {current} to {target}.",
            )
        stamp = _now()
        values: dict = {"status": target, "updated_at": stamp}
        if target == AlertStatus.ACKNOWLEDGED.value:
            values.update(acknowledged_at=stamp, acknowledged_by=actor_id)
        elif target == AlertStatus.RESOLVED.value:
            values.update(resolved_at=stamp, resolved_by=actor_id)
        else:
            values.update(suppressed_at=stamp, suppressed_by=actor_id)

        rows = self.db.execute(
            update(ThreatFinding)
            .where(ThreatFinding.id == finding.id, ThreatFinding.status == current)
            .values(**values)
        ).rowcount
        if rows != 1:
            self.db.rollback()
            self.db.refresh(finding)
            if finding.status == target:
                return finding
            raise IdentityError(
                ErrorCode.THREAT_FINDING_TRANSITION_INVALID,
                "The finding changed state concurrently; retry.",
            )
        self._audit(_TRANSITION_EVENT[target], finding.organization_id, actor_id,
                    meta={k: v for k, v in
                          {"finding_id": str(finding.id), "rule_id": finding.rule_id,
                           "from": current, "note": note}.items() if v})
        self.db.commit()
        self.db.refresh(finding)
        return finding


__all__ = ["ThreatFindingService"]
