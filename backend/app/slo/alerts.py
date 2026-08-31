"""Phase 4.7 -- the alert lifecycle (M4-4.7-FR-010..014, Gate K).

**One lifecycle, two evidence sources (§18).** :meth:`AlertService.raise_from_slo`
and :meth:`AlertService.raise_from_behavioral_finding` are the only two entry
points that create an alert, and each raises one *only when the evidence meets a
defined significance* -- an SLO evaluation that is ``BREACHED``, a behavioral
finding whose state is ``ANOMALOUS`` (not merely ``DEGRADED``). A ``DEGRADED``
finding stays a finding; escalation is explicit and threshold-defined, never
automatic (M4-4.7-FR-014, AC-08).

**One ongoing condition is one active alert (M4-4.7-FR-013, AC-07).** The
partial unique index ``uq_runtime_alerts_active_dedup`` on
``(organization_id, dedup_key) WHERE status IN ('OPEN','ACKNOWLEDGED')`` makes
the database decide the race. Re-raising an active condition bumps
``recurrence_count`` and ``last_seen_at``; re-raising a ``RESOLVED`` condition
**re-opens** that row; re-raising a ``SUPPRESSED`` condition does nothing --
that is what suppressing it means.

**A signal, never a notification, never enforcement.** This module writes rows
and audits transitions. It sends nothing: a test walks the AST and fails on any
delivery client. It stops nothing: Phase 4.3's engine is the only thing that
can halt an execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.models.runtime import BehavioralFinding, RuntimeAlert, SLODefinition
from app.slo.evaluator import SLOEvaluationResult
from app.slo.states import (
    ACTIVE_ALERT_STATUSES,
    ALLOWED_TRANSITIONS,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    max_severity,
)

#: A behavioral finding is significant enough to be an alert only at this state.
#: ``DEGRADED`` is a finding, not an alert -- the §18 "not every finding is an
#: alert" line, made concrete.
_SIGNIFICANT_FINDING_STATE = "ANOMALOUS"

_MAX_RAISE_ATTEMPTS = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slo_severity(budget_consumed: float | None) -> str:
    """Deterministic: how far past the error budget the breach is."""
    if budget_consumed is None:
        return AlertSeverity.WARNING.value
    if budget_consumed >= 3.0:
        return AlertSeverity.CRITICAL.value
    if budget_consumed >= 1.5:
        return AlertSeverity.HIGH.value
    return AlertSeverity.WARNING.value


class AlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Raising from evidence
    # ------------------------------------------------------------------ #
    def raise_from_slo(self, result: SLOEvaluationResult, *,
                       slo: SLODefinition) -> RuntimeAlert | None:
        """Raise (or sustain / re-open) an alert for a BREACHED SLO. Returns
        the alert, or ``None`` if the evaluation was not a breach or the
        condition is suppressed."""
        if not result.breached:
            return None
        dedup_key = f"slo:{result.slo_id}"
        severity = _slo_severity(result.budget_consumed)
        title = f"SLO breached: {slo.name}"
        observed = result.observed_value
        unit = "ms" if result.sli in ("latency_p95", "queue_delay") else ""
        summary = (
            f"{result.sli} over {slo.window} for {result.scope_type.lower()} scope "
            f"observed {_g(observed)}{unit} against a target of {_g(result.target)}{unit}; "
            f"error budget {_g(result.error_budget)} consumed "
            f"{(result.budget_consumed or 0) * 100:.0f}%."
        )
        return self._raise(
            organization_id=result.organization_id, source=AlertSource.SLO.value,
            source_id=result.evaluation_id, slo_id=result.slo_id, severity=severity,
            dedup_key=dedup_key, title=title, summary=summary,
            metric=result.sli, threshold_value=result.target,
            observed_value=observed, baseline_value=result.target,
            agent_id=result.scope_id if result.scope_type == "AGENT" else None,
            agent_version_id=result.scope_id if result.scope_type == "VERSION" else None,
            environment_id=result.scope_id if result.scope_type == "ENVIRONMENT" else None,
            context={"evidence": "slo_evaluation", "explanation": result.explanation},
        )

    def clear_from_slo(self, result: SLOEvaluationResult) -> RuntimeAlert | None:
        """A later evaluation reports the objective met -- resolve the active
        alert for this condition, if any. INSUFFICIENT_DATA/UNKNOWN neither
        raise nor clear: an alert's fate should not turn on a thin window."""
        if not result.met:
            return None
        return self._auto_resolve(result.organization_id, f"slo:{result.slo_id}",
                                  "the SLO evaluated MET in a later window")

    def raise_from_behavioral_finding(self, finding: BehavioralFinding) -> RuntimeAlert | None:
        """A behavioral finding of significance raises an alert (M4-4.7-FR-012).
        Significance = state ``ANOMALOUS``; a ``DEGRADED`` finding is a finding,
        not an alert (M4-4.7-FR-014)."""
        if finding.state != _SIGNIFICANT_FINDING_STATE:
            return None
        dedup_key = f"behavioral:{finding.agent_id}:{finding.signal_type}"
        title = f"Behavioral anomaly: {finding.signal_type}"
        summary = (
            f"{finding.signal_type} for this agent is ANOMALOUS on {finding.metric} "
            f"(observed {_g(finding.observed_value)}, threshold {_g(finding.threshold_value)}, "
            f"baseline {_g(finding.baseline_value)}); {finding.sample_count} samples in the window."
        )
        return self._raise(
            organization_id=finding.organization_id, source=AlertSource.BEHAVIORAL.value,
            source_id=finding.id, slo_id=None, severity=AlertSeverity.HIGH.value,
            dedup_key=dedup_key, title=title, summary=summary,
            metric=finding.metric,
            threshold_value=_num(finding.threshold_value),
            observed_value=_num(finding.observed_value),
            baseline_value=_num(finding.baseline_value),
            agent_id=finding.agent_id, agent_version_id=finding.agent_version_id,
            environment_id=finding.environment_id,
            context={"evidence": "behavioral_finding",
                     "explanation": dict(finding.explanation or {})},
        )

    def link_recent_behavioral_findings(self, organization_id: uuid.UUID, *,
                                        since: datetime) -> list[RuntimeAlert]:
        """Sweep ANOMALOUS behavioral findings evaluated since ``since`` and
        raise/link an alert for each. This is the one-directional bridge
        (``app.slo`` → ``app.behavior``): the behavior package is untouched and
        knows nothing about alerts."""
        findings = list(self.db.execute(
            select(BehavioralFinding).where(
                BehavioralFinding.organization_id == organization_id,
                BehavioralFinding.state == _SIGNIFICANT_FINDING_STATE,
                BehavioralFinding.evaluated_at >= since,
            ).order_by(BehavioralFinding.evaluated_at)
        ).scalars())
        raised: list[RuntimeAlert] = []
        for finding in findings:
            alert = self.raise_from_behavioral_finding(finding)
            if alert is not None:
                raised.append(alert)
        return raised

    # ------------------------------------------------------------------ #
    # The create-or-reopen primitive
    # ------------------------------------------------------------------ #
    def _raise(self, *, organization_id: uuid.UUID, source: str,
               source_id: uuid.UUID | None, slo_id: uuid.UUID | None,
               severity: str, dedup_key: str, title: str, summary: str,
               metric: str, threshold_value, observed_value, baseline_value,
               agent_id, agent_version_id, environment_id,
               context: dict) -> RuntimeAlert:
        for _ in range(_MAX_RAISE_ATTEMPTS):
            existing = self.db.execute(
                select(RuntimeAlert).where(
                    RuntimeAlert.organization_id == organization_id,
                    RuntimeAlert.dedup_key == dedup_key,
                ).order_by(RuntimeAlert.opened_at.desc())
            ).scalars().first()

            if existing is not None and existing.status == AlertStatus.SUPPRESSED.value:
                return existing  # suppressed: do not re-raise, do not mutate

            if existing is not None and existing.status in ACTIVE_ALERT_STATUSES:
                existing.recurrence_count += 1
                existing.last_seen_at = _now()
                existing.severity = max_severity(existing.severity, severity)
                existing.observed_value = observed_value
                existing.source_id = source_id or existing.source_id
                existing.context = context
                self.db.commit()
                return existing

            if existing is not None and existing.status == AlertStatus.RESOLVED.value:
                # A recurrence may raise severity, never lower it.
                reopen_severity = max_severity(existing.severity, severity)
                updated = self.db.execute(
                    _reopen_stmt(existing.id, reopen_severity, observed_value, source_id, context)
                ).rowcount
                if updated == 1:
                    self._audit(existing.id, organization_id,
                                AuthorizationAuditEvent.RUNTIME_ALERT_CREATED, None,
                                agent_id=agent_id,
                                meta={"reopened": True, "dedup_key": dedup_key,
                                      "severity": severity, "recurrence": True})
                    self.db.commit()
                    self.db.refresh(existing)
                    return existing
                self.db.rollback()
                continue  # lost the reopen race -- re-read

            # No prior alert for this condition -- create one.
            alert = RuntimeAlert(
                organization_id=organization_id, source=source, source_id=source_id,
                slo_id=slo_id, severity=severity, status=AlertStatus.OPEN.value,
                agent_id=agent_id, agent_version_id=agent_version_id,
                environment_id=environment_id, metric=metric,
                threshold_value=threshold_value, observed_value=observed_value,
                baseline_value=baseline_value, title=title, summary=summary,
                dedup_key=dedup_key, context=context, recurrence_count=1,
                opened_at=_now(), last_seen_at=_now(),
            )
            self.db.add(alert)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                continue  # another producer created the active alert -- re-read
            self._audit(alert.id, organization_id,
                        AuthorizationAuditEvent.RUNTIME_ALERT_CREATED, None,
                        agent_id=agent_id,
                        meta={"source": source, "dedup_key": dedup_key, "severity": severity})
            self.db.commit()
            self.db.refresh(alert)
            return alert

        raise RuntimeError("could not raise alert after retries")  # pragma: no cover

    def _auto_resolve(self, organization_id: uuid.UUID, dedup_key: str,
                      reason: str) -> RuntimeAlert | None:
        alert = self.db.execute(
            select(RuntimeAlert).where(
                RuntimeAlert.organization_id == organization_id,
                RuntimeAlert.dedup_key == dedup_key,
                RuntimeAlert.status.in_(tuple(ACTIVE_ALERT_STATUSES)),
            )
        ).scalars().first()
        if alert is None:
            return None
        alert.status = AlertStatus.RESOLVED.value
        alert.resolved_at = _now()
        alert.resolved_by = None  # system
        alert.context = {**(alert.context or {}), "auto_resolved": reason}
        self._audit(alert.id, organization_id,
                    AuthorizationAuditEvent.RUNTIME_ALERT_RESOLVED, None,
                    agent_id=alert.agent_id,
                    meta={"auto": True, "reason": reason})
        self.db.commit()
        self.db.refresh(alert)
        return alert

    # ------------------------------------------------------------------ #
    # Operator transitions
    # ------------------------------------------------------------------ #
    def transition(self, alert: RuntimeAlert, target: str, actor_id: uuid.UUID,
                   *, note: str | None = None) -> RuntimeAlert:
        """Move an alert to ``target`` (ACKNOWLEDGED / RESOLVED / SUPPRESSED).

        Optimistic: the UPDATE is conditional on the current status, so two
        operators acking the same alert converge -- the second finds the alert
        already in the target state and returns it rather than tearing the
        status."""
        from app.identity.errors import ErrorCode, IdentityError

        current = alert.status
        if current == target:
            return alert  # idempotent: converge rather than error
        if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise IdentityError(
                ErrorCode.ALERT_TRANSITION_INVALID,
                f"Cannot move an alert from {current} to {target}.")

        stamp = _now()
        values: dict = {"status": target, "updated_at": stamp}
        event: AuthorizationAuditEvent
        if target == AlertStatus.ACKNOWLEDGED.value:
            values.update(acknowledged_at=stamp, acknowledged_by=actor_id)
            event = AuthorizationAuditEvent.RUNTIME_ALERT_ACKNOWLEDGED
        elif target == AlertStatus.RESOLVED.value:
            values.update(resolved_at=stamp, resolved_by=actor_id)
            event = AuthorizationAuditEvent.RUNTIME_ALERT_RESOLVED
        else:  # SUPPRESSED
            values.update(suppressed_at=stamp)
            event = AuthorizationAuditEvent.RUNTIME_ALERT_SUPPRESSED

        from sqlalchemy import update

        rows = self.db.execute(
            update(RuntimeAlert)
            .where(RuntimeAlert.id == alert.id, RuntimeAlert.status == current)
            .values(**values)
        ).rowcount
        if rows != 1:
            self.db.rollback()
            self.db.refresh(alert)
            if alert.status == target:
                return alert  # someone else got there first -- converge
            raise IdentityError(
                ErrorCode.ALERT_TRANSITION_INVALID,
                "The alert changed state concurrently; retry.")

        self._audit(alert.id, alert.organization_id, event, actor_id,
                    agent_id=alert.agent_id,
                    meta={k: v for k, v in {"note": note, "from": current}.items() if v})
        self.db.commit()
        self.db.refresh(alert)
        return alert

    # ------------------------------------------------------------------ #
    def _audit(self, alert_id: uuid.UUID, organization_id: uuid.UUID,
               event: AuthorizationAuditEvent, actor_id: uuid.UUID | None, *,
               agent_id: uuid.UUID | None, meta: dict) -> None:
        from app.authorization.services import AuthorizationAuditService

        AuthorizationAuditService(self.db).record_change(
            event, organization_id=organization_id, actor_id=actor_id,
            meta={**meta, "alert_id": str(alert_id)})


def _reopen_stmt(alert_id, severity, observed_value, source_id, context):
    from sqlalchemy import update

    return (
        update(RuntimeAlert)
        .where(RuntimeAlert.id == alert_id, RuntimeAlert.status == "RESOLVED")
        .values(status="OPEN", resolved_at=None, resolved_by=None,
                acknowledged_at=None, acknowledged_by=None,
                last_seen_at=_now(), updated_at=_now(),
                recurrence_count=RuntimeAlert.recurrence_count + 1,
                severity=severity, observed_value=observed_value,
                source_id=source_id, context=context)
    )


def _num(value) -> float | None:
    return float(value) if value is not None else None


def _g(value) -> str:
    return f"{float(value):.4g}" if value is not None else "n/a"
