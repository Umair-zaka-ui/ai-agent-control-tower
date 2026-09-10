"""Phase 5.5 (M5.5) - ``PostureFindingService``: the finding lifecycle.

The 4.7 alert lifecycle, applied to posture findings (ADR-0019). Mirrors
``app.slo.alerts.AlertService`` primitive-for-primitive:

  * **One open finding per condition.** The partial unique index
    ``uq_posture_findings_active`` on ``(organization_id, dedup_key) WHERE
    status IN ('OPEN','ACKNOWLEDGED')`` makes the database decide the race. A
    re-evaluation of a still-true condition bumps ``recurrence_count`` and
    ``last_seen_at``. A ``RESOLVED`` finding **re-opens** on recurrence; a
    ``SUPPRESSED`` one does not - that is what suppressing it means.

  * **Auto-resolve on clear.** When a rule evaluates and its condition no
    longer holds, ``auto_resolve`` closes the open finding for that condition
    (system-resolved, audited).

  * **A signal, never enforcement.** This module writes rows and audits
    transitions. It stops nothing - the 4.3 engine + kill switch are the only
    things that can halt an execution. Asserted over the AST
    (``test_ac07``), the containment-by-absence Phases 4.4/4.5 shipped.
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
from app.models.posture import PostureFinding
from app.slo.states import ACTIVE_ALERT_STATUSES, ALLOWED_TRANSITIONS, AlertStatus, max_severity

_MAX_RAISE_ATTEMPTS = 4

_TRANSITION_EVENT = {
    "ACKNOWLEDGED": AuthorizationAuditEvent.POSTURE_FINDING_ACKNOWLEDGED,
    "RESOLVED": AuthorizationAuditEvent.POSTURE_FINDING_RESOLVED,
    "SUPPRESSED": AuthorizationAuditEvent.POSTURE_FINDING_SUPPRESSED,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostureFindingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def _audit(self, event: AuthorizationAuditEvent, organization_id: uuid.UUID,
               actor_id: uuid.UUID | None, *, meta: dict) -> None:
        AuthorizationAuditService(self.db).record_change(
            event, organization_id=organization_id, actor_id=actor_id, meta=meta
        )

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor, finding_id: uuid.UUID) -> PostureFinding:
        f = self.db.get(PostureFinding, finding_id)
        if f is None or f.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.POSTURE_FINDING_NOT_FOUND, "Posture finding not found.")
        return f

    # ------------------------------------------------------------------ #
    # the create-or-reopen primitive (mirrors AlertService._raise)
    # ------------------------------------------------------------------ #
    def raise_finding(
        self,
        *,
        organization_id: uuid.UUID,
        rule_id: str,
        control_id: str | None,
        rule_version: str,
        ruleset_version: str,
        outcome: str,
        severity: str,
        subject_type: str,
        subject_id: uuid.UUID,
        reason: str,
        remediation: str,
        evidence: dict,
        governing_policy: dict,
        dedup_key: str,
    ) -> PostureFinding:
        for _ in range(_MAX_RAISE_ATTEMPTS):
            existing = self.db.execute(
                select(PostureFinding).where(
                    PostureFinding.organization_id == organization_id,
                    PostureFinding.dedup_key == dedup_key,
                ).order_by(PostureFinding.first_seen_at.desc())
            ).scalars().first()

            if existing is not None and existing.status == AlertStatus.SUPPRESSED.value:
                return existing  # suppressed: do not re-raise, do not mutate

            if existing is not None and existing.status in ACTIVE_ALERT_STATUSES:
                existing.recurrence_count += 1
                existing.last_seen_at = _now()
                existing.severity = max_severity(existing.severity, severity)
                existing.reason = reason
                existing.remediation = remediation
                existing.evidence = evidence
                existing.governing_policy = governing_policy
                existing.rule_version = rule_version
                existing.ruleset_version = ruleset_version
                existing.outcome = outcome
                existing.updated_at = _now()
                self.db.commit()
                self.db.refresh(existing)
                return existing

            if existing is not None and existing.status == AlertStatus.RESOLVED.value:
                reopen_severity = max_severity(existing.severity, severity)
                updated = self.db.execute(
                    update(PostureFinding)
                    .where(PostureFinding.id == existing.id, PostureFinding.status == "RESOLVED")
                    .values(
                        status="OPEN", resolved_at=None, resolved_by=None,
                        acknowledged_at=None, acknowledged_by=None,
                        last_seen_at=_now(), updated_at=_now(),
                        recurrence_count=PostureFinding.recurrence_count + 1,
                        severity=reopen_severity, reason=reason, remediation=remediation,
                        evidence=evidence, governing_policy=governing_policy,
                        rule_version=rule_version, ruleset_version=ruleset_version, outcome=outcome,
                    )
                ).rowcount
                if updated == 1:
                    self._audit(AuthorizationAuditEvent.POSTURE_FINDING_REOPENED, organization_id, None,
                                meta={"finding_id": str(existing.id), "rule_id": rule_id,
                                      "dedup_key": dedup_key, "severity": reopen_severity})
                    self.db.commit()
                    self.db.refresh(existing)
                    return existing
                self.db.rollback()
                continue  # lost the reopen race -- re-read

            finding = PostureFinding(
                organization_id=organization_id, rule_id=rule_id, control_id=control_id,
                rule_version=rule_version, ruleset_version=ruleset_version, outcome=outcome,
                severity=severity, status=AlertStatus.OPEN.value,
                subject_type=subject_type, subject_id=subject_id,
                reason=reason, remediation=remediation, evidence=evidence,
                governing_policy=governing_policy, dedup_key=dedup_key, recurrence_count=1,
                first_seen_at=_now(), last_seen_at=_now(),
            )
            self.db.add(finding)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                continue  # another evaluator opened the active finding -- re-read
            self._audit(AuthorizationAuditEvent.POSTURE_FINDING_OPENED, organization_id, None,
                        meta={"finding_id": str(finding.id), "rule_id": rule_id,
                              "dedup_key": dedup_key, "severity": severity, "outcome": outcome})
            self.db.commit()
            self.db.refresh(finding)
            return finding

        raise RuntimeError("could not raise posture finding after retries")  # pragma: no cover

    def auto_resolve(self, organization_id: uuid.UUID, dedup_key: str, reason: str) -> PostureFinding | None:
        finding = self.db.execute(
            select(PostureFinding).where(
                PostureFinding.organization_id == organization_id,
                PostureFinding.dedup_key == dedup_key,
                PostureFinding.status.in_(tuple(ACTIVE_ALERT_STATUSES)),
            )
        ).scalars().first()
        if finding is None:
            return None
        finding.status = AlertStatus.RESOLVED.value
        finding.resolved_at = _now()
        finding.resolved_by = None
        finding.updated_at = _now()
        finding.evidence = {**(finding.evidence or {}), "auto_resolved": reason}
        self._audit(AuthorizationAuditEvent.POSTURE_FINDING_RESOLVED, organization_id, None,
                    meta={"finding_id": str(finding.id), "auto": True, "reason": reason})
        self.db.commit()
        self.db.refresh(finding)
        return finding

    # ------------------------------------------------------------------ #
    # operator transitions (mirrors AlertService.transition)
    # ------------------------------------------------------------------ #
    def transition(self, finding: PostureFinding, target: str, actor_id: uuid.UUID,
                   *, note: str | None = None) -> PostureFinding:
        current = finding.status
        if current == target:
            return finding  # idempotent: converge rather than error
        if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise IdentityError(
                ErrorCode.POSTURE_FINDING_TRANSITION_INVALID,
                f"Cannot move a posture finding from {current} to {target}.",
            )
        stamp = _now()
        values: dict = {"status": target, "updated_at": stamp}
        if target == AlertStatus.ACKNOWLEDGED.value:
            values.update(acknowledged_at=stamp, acknowledged_by=actor_id)
        elif target == AlertStatus.RESOLVED.value:
            values.update(resolved_at=stamp, resolved_by=actor_id)
        else:  # SUPPRESSED
            values.update(suppressed_at=stamp, suppressed_by=actor_id)

        rows = self.db.execute(
            update(PostureFinding)
            .where(PostureFinding.id == finding.id, PostureFinding.status == current)
            .values(**values)
        ).rowcount
        if rows != 1:
            self.db.rollback()
            self.db.refresh(finding)
            if finding.status == target:
                return finding  # someone else got there first -- converge
            raise IdentityError(
                ErrorCode.POSTURE_FINDING_TRANSITION_INVALID,
                "The finding changed state concurrently; retry.",
            )
        self._audit(_TRANSITION_EVENT[target], finding.organization_id, actor_id,
                    meta={k: v for k, v in
                          {"finding_id": str(finding.id), "rule_id": finding.rule_id,
                           "from": current, "note": note}.items() if v})
        self.db.commit()
        self.db.refresh(finding)
        return finding


__all__ = ["PostureFindingService"]
