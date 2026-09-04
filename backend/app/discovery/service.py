"""Phase 5.2 (M5.2) - ``DiscoverySourceService`` (config) and
``DiscoveryRunService`` (the sweep).

**The transaction boundaries here are the phase**, exactly as
``app/scheduler/service.py``'s own module docstring says of itself. There are
three short transactions per run, with the external fetch held strictly
between the first and second, touching no database session at all:

1. **Start.** Insert a ``PENDING``/``RUNNING`` ``discovery_runs`` row -> COMMIT.
2. **The fetch.** ``adapter.fetch(client, ...)`` -- pure network I/O through
   ``GovernedHttpClient``. No ``Session`` is in scope for this call; the
   adapter contract's ``fetch()`` signature does not accept one (see
   ``app/discovery/adapters/base.py``). **No DB lock or open transaction is
   held here** -- the M1 deadlock lesson (``ToolLoopOrchestrator``,
   ``SchedulerService``), extended to external discovery I/O for the first
   time in this milestone.
3. **Persist + reconcile.** Observations are inserted (each in its own
   SAVEPOINT, so one malformed item cannot poison the batch -- the same
   technique ``app.observability.events.emit`` uses for telemetry), then
   ``ReconciliationService`` derives canonical state, each step its own short
   commit.
4. **Finish.** Re-read the run, record the outcome -> COMMIT.

A run never raises out to its caller for anything the source itself did
(rate limit, partial page, outage) -- SRS M5.2 §11, "fails open". It raises
only for a genuine programming/configuration error (unknown adapter,
malformed source config).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.discovery.adapters import registry as adapter_registry
from app.discovery.reconciliation import ReconciliationService
from app.identity.errors import ErrorCode, IdentityError
from app.models.discovery import DiscoveryObservation, DiscoveryRun, DiscoverySource
from app.models.user import User
from app.observability.scrubbing import scrub
from app.runtime.services import _now, _record_event

# Bounded to Agent.external_reference's own length (5.1), not
# DiscoveryObservation.external_identifier's more generous VARCHAR(500) --
# this is the one choke point every external identifier passes through
# before matching/creation, so reconciliation and staleness's re-observation
# check always agree on the same (possibly truncated) value.
_MAX_EXTERNAL_IDENTIFIER = 255


class DiscoverySourceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, source_id: uuid.UUID) -> DiscoverySource:
        source = self.db.get(DiscoverySource, source_id)
        if source is None or source.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DISCOVERY_SOURCE_NOT_FOUND, "Discovery source not found.")
        return source

    def list(self, actor: User) -> list[DiscoverySource]:
        return list(self.db.execute(
            select(DiscoverySource).where(DiscoverySource.organization_id == actor.organization_id)
            .order_by(DiscoverySource.created_at.desc())
        ).scalars())

    def list_enabled(self, organization_id: uuid.UUID) -> list[DiscoverySource]:
        return list(self.db.execute(
            select(DiscoverySource).where(DiscoverySource.organization_id == organization_id,
                                          DiscoverySource.enabled.is_(True))
        ).scalars())

    def create(self, actor: User, *, name: str, adapter_key: str, config: dict,
              secret: str | None = None, enabled: bool = True,
              missed_sweeps_before_stale: int = 1) -> DiscoverySource:
        adapter = adapter_registry.resolve(adapter_key)
        adapter.validate_configuration(config)

        encrypted_secret, secret_hint = None, None
        if secret:
            from app.runtime.providers.credential_crypto import encrypt_secret, mask_hint
            encrypted_secret, secret_hint = encrypt_secret(secret), mask_hint(secret)

        source = DiscoverySource(
            organization_id=actor.organization_id, name=name, adapter_key=adapter_key,
            config=config, encrypted_secret=encrypted_secret, secret_hint=secret_hint,
            enabled=enabled, missed_sweeps_before_stale=max(1, missed_sweeps_before_stale),
            created_by=actor.id,
        )
        self.db.add(source)
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_SOURCE_CREATED, actor,
                     organization_id=actor.organization_id,
                     meta={"source_name": name, "adapter_key": adapter_key})
        self.db.commit()
        self.db.refresh(source)
        return source

    def update(self, actor: User, source_id: uuid.UUID, *, enabled: bool | None = None,
              config: dict | None = None, secret: str | None = None,
              missed_sweeps_before_stale: int | None = None) -> DiscoverySource:
        source = self.get_or_404(actor, source_id)
        if config is not None:
            adapter_registry.resolve(source.adapter_key).validate_configuration(config)
            source.config = config
        if enabled is not None:
            source.enabled = enabled
        if missed_sweeps_before_stale is not None:
            source.missed_sweeps_before_stale = max(1, missed_sweeps_before_stale)
        if secret is not None:
            from app.runtime.providers.credential_crypto import encrypt_secret, mask_hint
            source.encrypted_secret, source.secret_hint = encrypt_secret(secret), mask_hint(secret)

        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_SOURCE_UPDATED, actor,
                     organization_id=actor.organization_id,
                     meta={"source_name": source.name, "enabled": source.enabled})
        self.db.commit()
        self.db.refresh(source)
        return source

    def resolve_secret(self, source: DiscoverySource) -> str | None:
        if not source.encrypted_secret:
            return None
        from app.runtime.providers.credential_crypto import decrypt_secret
        return decrypt_secret(source.encrypted_secret)


class DiscoveryRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, run_id: uuid.UUID) -> DiscoveryRun:
        run = self.db.get(DiscoveryRun, run_id)
        if run is None or run.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DISCOVERY_RUN_NOT_FOUND, "Discovery run not found.")
        return run

    def list_for_source(self, actor: User, source_id: uuid.UUID) -> list[DiscoveryRun]:
        DiscoverySourceService(self.db).get_or_404(actor, source_id)
        return list(self.db.execute(
            select(DiscoveryRun).where(DiscoveryRun.source_id == source_id)
            .order_by(DiscoveryRun.created_at.desc())
        ).scalars())

    # ------------------------------------------------------------------ #
    # Transaction 1 -- start (commits before the fetch)
    # ------------------------------------------------------------------ #
    def _start(self, source: DiscoverySource, *, trigger: str) -> DiscoveryRun:
        run = DiscoveryRun(organization_id=source.organization_id, source_id=source.id,
                           status="RUNNING", trigger=trigger, started_at=_now(), checkpoint={})
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # ------------------------------------------------------------------ #
    # Transaction 3 -- finish
    # ------------------------------------------------------------------ #
    def _finish(self, actor: User, run: DiscoveryRun, source: DiscoverySource, *, status: str,
               error: str | None = None, checkpoint: dict | None = None) -> DiscoveryRun:
        run.status = status
        run.ended_at = _now()
        run.error = error[:2000] if error else None
        if checkpoint is not None:
            run.checkpoint = checkpoint
        source.last_run_at = run.ended_at
        source.last_run_status = status
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_RUN_COMPLETED, actor,
                     organization_id=source.organization_id,
                     meta={"source_id": str(source.id), "run_id": str(run.id), "status": status,
                           "observations": run.observations_count, "agents_created": run.agents_created,
                           "agents_linked": run.agents_linked, "findings": run.findings_created})
        self.db.commit()
        self.db.refresh(run)
        return run

    def _persist_observations(self, run: DiscoveryRun, observations) -> list[DiscoveryObservation]:
        """Transaction 3a. Each row its own SAVEPOINT -- one malformed
        observation cannot poison the batch (the ``app.observability.events``
        SAVEPOINT technique, applied here to domain evidence rather than
        telemetry)."""
        persisted: list[DiscoveryObservation] = []
        now = _now()
        for obs in observations:
            try:
                with self.db.begin_nested():
                    row = DiscoveryObservation(
                        organization_id=run.organization_id, source_id=run.source_id, run_id=run.id,
                        external_identifier=obs.external_identifier[:_MAX_EXTERNAL_IDENTIFIER],
                        normalized_payload=scrub({
                            "name": obs.name, "agent_type": obs.agent_type,
                            "origin_provider": obs.origin_provider, "description": obs.description,
                            "raw": obs.raw,
                        }),
                        confidence=obs.confidence, observed_at=now,
                    )
                    self.db.add(row)
                self.db.flush()
                persisted.append(row)
            except Exception:  # noqa: BLE001 - one bad observation must not stop the batch
                self.db.rollback()
        self.db.commit()
        return persisted

    # ------------------------------------------------------------------ #
    # The sweep, called by the scheduler handler or a manual-trigger route.
    # ------------------------------------------------------------------ #
    def _last_checkpoint(self, source: DiscoverySource) -> dict | None:
        """Resumption reads the most recent PARTIAL run's checkpoint for
        this source -- a fresh (non-partial) run always starts at offset
        zero; a bounded/degraded one picks up where it left off."""
        last = self.db.execute(
            select(DiscoveryRun).where(DiscoveryRun.source_id == source.id, DiscoveryRun.status == "PARTIAL")
            .order_by(DiscoveryRun.created_at.desc()).limit(1)
        ).scalars().first()
        return last.checkpoint if last and last.checkpoint else None

    def run_source(self, actor: User, source: DiscoverySource, *, trigger: str) -> DiscoveryRun:
        resume_checkpoint = self._last_checkpoint(source)
        run = self._start(source, trigger=trigger)
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_RUN_STARTED, actor,
                     organization_id=source.organization_id,
                     meta={"source_id": str(source.id), "run_id": str(run.id), "trigger": trigger})
        self.db.commit()

        adapter = adapter_registry.resolve(source.adapter_key)
        try:
            client = adapter.build_client(source.config)
            secret = DiscoverySourceService(self.db).resolve_secret(source)
            # ---- THE no-lock-across-external-I/O boundary (M5.2-AC-06) ----
            # `self.db` is not referenced again until this call returns.
            fetch_result = adapter.fetch(client, source.config, secret, resume_checkpoint)
            normalized = [adapter.normalize(item) for item in fetch_result.items]
        except IdentityError as exc:
            return self._finish(actor, run, source, status="FAILED", error=exc.message)
        except Exception as exc:  # noqa: BLE001 - a source's own failure must not crash the sweep
            return self._finish(actor, run, source, status="FAILED", error=str(exc)[:2000])

        persisted = self._persist_observations(run, normalized)
        run.observations_count = len(persisted)

        recon = ReconciliationService(self.db).reconcile(actor, run, source, persisted)
        run.agents_created = recon["created"]
        run.agents_linked = recon["linked"]
        run.findings_created = recon["flagged"]

        stale = ReconciliationService(self.db).check_staleness(
            actor, source, observed_external_ids={o.external_identifier for o in persisted})
        run.findings_created += stale["raised"]
        self.db.commit()

        final_status = "SUCCEEDED"
        if fetch_result.degraded:
            final_status = "PARTIAL"
        return self._finish(actor, run, source, status=final_status,
                           error=fetch_result.degraded_reason, checkpoint=fetch_result.next_checkpoint)


class DiscoveryFindingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, finding_id: uuid.UUID):
        from app.models.discovery import DiscoveryFinding

        finding = self.db.get(DiscoveryFinding, finding_id)
        if finding is None or finding.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DISCOVERY_FINDING_NOT_FOUND, "Discovery finding not found.")
        return finding

    def list(self, actor: User, *, status: str | None = None) -> list:
        from app.models.discovery import DiscoveryFinding

        stmt = select(DiscoveryFinding).where(DiscoveryFinding.organization_id == actor.organization_id)
        if status:
            stmt = stmt.where(DiscoveryFinding.status == status)
        return list(self.db.execute(stmt.order_by(DiscoveryFinding.created_at.desc())).scalars())

    def resolve(self, actor: User, finding_id: uuid.UUID, *, status: str):
        finding = self.get_or_404(actor, finding_id)
        if finding.status != "OPEN":
            raise IdentityError(ErrorCode.DISCOVERY_FINDING_ALREADY_RESOLVED,
                               f"This finding is already {finding.status}.")
        finding.status = status
        finding.resolved_by = actor.id
        finding.resolved_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_FINDING_RESOLVED, actor,
                     organization_id=actor.organization_id, agent_id=finding.agent_id,
                     meta={"finding_id": str(finding.id), "finding_type": finding.finding_type,
                           "new_status": status})
        self.db.commit()
        self.db.refresh(finding)
        return finding


__all__ = ["DiscoverySourceService", "DiscoveryRunService", "DiscoveryFindingService"]
