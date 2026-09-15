"""Phase 5.9 (M5.9) - evaluating assurance controls and exporting evidence.

**This module reads. It never writes evidence, only conclusions about it.** The
evidence lives where M1-5.8 put it; an evaluation row records what a control saw
there and when. Nothing here creates an audit entry that stands in for an
absent one, and nothing here infers evidence that was not recorded.

**Idempotent by replacement, not accumulation.** Re-evaluating replaces the
prior result for the same (control, subject) rather than appending, because an
assurance view must answer "what is true now" without a reader having to pick
the newest row and hope they picked right. History is not lost: every export is
recorded with a digest, and the audit trail carries the evaluation events.

**Export says whether it is signed.** When M4.11's signing provider is
available the bundle carries a DSSE envelope over the canonicalized document -
the same envelope shape, provider and key service Phase M4.11 uses for version
attestations, reused rather than reimplemented. When signing is unavailable the
bundle exports **unsigned and says so in the result**; silently returning an
unsigned bundle that a recipient assumes is tamper-evident would be worse than
refusing, and refusing outright would deny an auditor evidence they can still
use with their own chain of custody.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.assurance import frameworks
from app.assurance.controls import (
    ASSURANCE_CATALOG_VERSION,
    CONTROLS,
    CONTROLS_BY_ID,
    DEFAULT_FRESHNESS_DAYS,
    AssuranceContext,
)
from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.assurance import AssuranceEvaluation, AssuranceEvidenceBundle
from app.models.user import User

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EvaluationSummary:
    """Counts by result. Deliberately **not** a score or a percentage.

    A "78% compliant" figure would need a denominator ACT does not know - the
    full control set in the customer's chosen audit scope - and would compress
    INSUFFICIENT_EVIDENCE into the same number as PASS or FAIL, which is the one
    thing this phase must never do. Three counts, reported separately, say
    exactly what is known and what is not.
    """

    evaluated: int
    passed: int
    failed: int
    insufficient: int
    stale: int

    def as_dict(self) -> dict:
        return {"evaluated": self.evaluated, "passed": self.passed,
                "failed": self.failed, "insufficient_evidence": self.insufficient,
                "stale": self.stale}


class AssuranceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def _agent_or_404(self, actor: User, agent_id: uuid.UUID) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.ASSURANCE_SUBJECT_NOT_FOUND,
                                "No such agent in this organization.")
        return agent

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    def evaluate_agent(self, actor: User, agent: Agent, *,
                       freshness_days: int = DEFAULT_FRESHNESS_DAYS,
                       audit: bool = True) -> list[AssuranceEvaluation]:
        """Evaluate every agent-scoped control against this agent's evidence.

        Deterministic: the controls are pure functions of the evidence, so a
        re-run over unchanged evidence produces identical results. The prior
        results for this subject are replaced rather than added to, so the
        table always answers "what is true now".
        """
        ctx = AssuranceContext(self.db, actor.organization_id, agent=agent,
                               freshness_days=freshness_days)
        rows: list[AssuranceEvaluation] = []
        for control in CONTROLS:
            if control.scope != "AGENT":
                continue
            outcome = control.evaluate(ctx)
            rows.append(AssuranceEvaluation(
                organization_id=actor.organization_id,
                control_id=control.id,
                catalog_version=ASSURANCE_CATALOG_VERSION,
                scope="AGENT",
                subject_id=agent.id,
                result=outcome.result,
                reason=outcome.reason,
                evidence=_json_safe(outcome.evidence),
                evidence_as_of=outcome.as_of,
                stale=outcome.stale,
                remediation=outcome.remediation or None,
                evaluated_at=_now(),
            ))

        # Replace, preserving any documented exception an operator recorded
        # against this control — an exception is a human decision and must not
        # be silently discarded by a routine re-evaluation.
        existing = {e.control_id: e for e in self.db.execute(
            select(AssuranceEvaluation).where(
                AssuranceEvaluation.organization_id == actor.organization_id,
                AssuranceEvaluation.subject_id == agent.id)
        ).scalars()}
        for row in rows:
            prior = existing.get(row.control_id)
            if prior is not None and prior.exception_reason:
                row.exception_reason = prior.exception_reason
                row.exception_by = prior.exception_by
                row.exception_at = prior.exception_at

        self.db.execute(delete(AssuranceEvaluation).where(
            AssuranceEvaluation.organization_id == actor.organization_id,
            AssuranceEvaluation.subject_id == agent.id))
        self.db.add_all(rows)
        if audit:
            AuthorizationAuditService(self.db).record_change(
                AuthorizationAuditEvent.ASSURANCE_EVALUATED,
                organization_id=actor.organization_id, actor_id=actor.id,
                identity_id=agent.id,
                meta={"scope": "AGENT", "agent_id": str(agent.id),
                      "catalog_version": ASSURANCE_CATALOG_VERSION,
                      **summarize(rows).as_dict()},
            )
        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        return rows

    def evaluate_tenant(self, actor: User, *,
                        freshness_days: int = DEFAULT_FRESHNESS_DAYS) -> EvaluationSummary:
        """The 3.8-schedulable sweep. Registered as a handler; no new scheduler."""
        agents = list(self.db.execute(
            select(Agent).where(Agent.organization_id == actor.organization_id)
        ).scalars())
        all_rows: list[AssuranceEvaluation] = []
        for agent in agents:
            all_rows.extend(self.evaluate_agent(actor, agent,
                                                freshness_days=freshness_days, audit=False))
        summary = summarize(all_rows)
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.ASSURANCE_EVALUATED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"scope": "ORGANIZATION", "agents": len(agents),
                  "catalog_version": ASSURANCE_CATALOG_VERSION, **summary.as_dict()},
        )
        self.db.commit()
        return summary

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def evaluations(self, actor: User, *, subject_id: uuid.UUID | None = None,
                    control_id: str | None = None, result: str | None = None,
                    limit: int = 500) -> list[AssuranceEvaluation]:
        stmt = select(AssuranceEvaluation).where(
            AssuranceEvaluation.organization_id == actor.organization_id)
        if subject_id:
            stmt = stmt.where(AssuranceEvaluation.subject_id == subject_id)
        if control_id:
            stmt = stmt.where(AssuranceEvaluation.control_id == control_id)
        if result:
            stmt = stmt.where(AssuranceEvaluation.result == result)
        return list(self.db.execute(
            stmt.order_by(AssuranceEvaluation.control_id).limit(limit)).scalars())

    def framework_report(self, actor: User, framework_id: str) -> dict:
        """Evidence mapped to one framework's controls.

        Returns mappings and their evaluations. It does **not** return a score,
        a coverage percentage or a status — see ``app/assurance/frameworks.py``
        for why an aggregate here would be a claim ACT is not entitled to make.
        """
        fw = frameworks.FRAMEWORKS_BY_ID.get(framework_id)
        if fw is None:
            raise IdentityError(ErrorCode.ASSURANCE_FRAMEWORK_UNKNOWN,
                                f"{framework_id!r} is not a mapped framework.")
        rows = self.evaluations(actor, limit=5000)
        by_control: dict[str, list[AssuranceEvaluation]] = {}
        for row in rows:
            by_control.setdefault(row.control_id, []).append(row)

        mapped = []
        for m in frameworks.mappings_for(framework_id):
            evals = [e for cid in m.act_control_ids for e in by_control.get(cid, [])]
            mapped.append({
                "control_ref": m.control_ref,
                "title": m.title,
                "rationale": m.rationale,
                "act_control_ids": list(m.act_control_ids),
                "evaluations": [_eval_payload(e) for e in evals],
                # Stated per control, not summed across the framework.
                "counts": summarize(evals).as_dict(),
                "evidence_available": bool(evals),
            })
        return {
            "framework": {"id": fw.id, "name": fw.name, "revision": fw.revision,
                          "scope_note": fw.scope_note},
            "mapping_version": frameworks.MAPPING_VERSION,
            "catalog_version": ASSURANCE_CATALOG_VERSION,
            "generated_at": _now().isoformat(),
            "controls": mapped,
            # The sentence that must travel with every rendering of this data.
            "disclaimer": (
                "ACT maps evidence it holds to these control references. This is not a "
                "compliance determination, a certification, or an audit opinion — those "
                "are judgements only an accredited assessor can make."
            ),
        }

    # ------------------------------------------------------------------ #
    # Exceptions
    # ------------------------------------------------------------------ #
    def record_exception(self, actor: User, evaluation_id: uuid.UUID, *,
                         reason: str) -> AssuranceEvaluation:
        """Document an accepted risk against one evaluation.

        It does **not** change the result. A FAIL with an exception still reads
        FAIL — the exception records that someone accepted it, who, and why, so
        an auditor sees both the finding and the decision. An exception that
        flipped the result to PASS would be indistinguishable from the control
        actually being met, which is the fabrication this phase forbids.
        """
        row = self.db.get(AssuranceEvaluation, evaluation_id)
        if row is None or row.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.ASSURANCE_EVALUATION_NOT_FOUND,
                                "No such evaluation.")
        row.exception_reason = reason
        row.exception_by = actor.id
        row.exception_at = _now()
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.ASSURANCE_EXCEPTION_RECORDED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"evaluation_id": str(row.id), "control_id": row.control_id,
                  "result": row.result, "reason": reason,
                  "subject_id": str(row.subject_id) if row.subject_id else None},
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    # ------------------------------------------------------------------ #
    # Evidence export
    # ------------------------------------------------------------------ #
    def export_bundle(self, actor: User, *, framework_id: str | None = None,
                      subject_id: uuid.UUID | None = None) -> dict:
        """Build, record and (where possible) sign an evidence bundle.

        Tenant-scoped by construction: every row read is filtered by the
        caller's organization, so a bundle cannot contain another tenant's
        evidence even if a subject id from elsewhere is supplied — it simply
        matches nothing.
        """
        if subject_id is not None:
            self._agent_or_404(actor, subject_id)

        rows = self.evaluations(actor, subject_id=subject_id, limit=5000)
        document = {
            "act_evidence_bundle": "1",
            "organization_id": str(actor.organization_id),
            "generated_at": _now().isoformat(),
            "catalog_version": ASSURANCE_CATALOG_VERSION,
            "mapping_version": frameworks.MAPPING_VERSION,
            "scope": "AGENT" if subject_id else "ORGANIZATION",
            "subject_id": str(subject_id) if subject_id else None,
            "evaluations": [_eval_payload(r) for r in rows],
            "counts": summarize(rows).as_dict(),
            "disclaimer": (
                "Evidence and control mappings only. ACT makes no compliance "
                "determination, certification or audit opinion."
            ),
        }
        if framework_id:
            document["framework"] = self.framework_report(actor, framework_id)

        payload, digest, signature, key_id, signed = self._sign(document)

        record = AssuranceEvidenceBundle(
            organization_id=actor.organization_id,
            framework_id=framework_id,
            scope=document["scope"],
            subject_id=subject_id,
            catalog_version=ASSURANCE_CATALOG_VERSION,
            mapping_version=frameworks.MAPPING_VERSION,
            content_digest=digest,
            signature=signature,
            signing_key_id=key_id,
            evaluation_count=len(rows),
            exported_by=actor.id,
        )
        self.db.add(record)
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.ASSURANCE_EVIDENCE_EXPORTED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"scope": document["scope"], "framework_id": framework_id,
                  "subject_id": str(subject_id) if subject_id else None,
                  "content_digest": digest, "signed": signed,
                  "evaluation_count": len(rows)},
        )
        self.db.commit()
        self.db.refresh(record)

        return {
            "bundle_id": str(record.id),
            "content_digest": digest,
            "signed": signed,
            "signature": signature,
            "signing_key_id": key_id,
            # Said out loud rather than inferred from a null signature: a
            # recipient must not assume tamper-evidence the bundle lacks.
            "tamper_evidence": (
                "DSSE-signed; recompute the digest over the canonical document and verify "
                "the signature against the named key."
                if signed else
                "UNSIGNED — signing was unavailable. This bundle carries no cryptographic "
                "tamper-evidence; treat its chain of custody as your own responsibility."
            ),
            "document": document,
        }


    def _sign(self, document: dict) -> tuple[bytes, str, dict | None, str | None, bool]:
        """Canonicalize, digest and DSSE-sign, reusing M4.11's own primitives.

        Signing failure is caught deliberately, and the asymmetry with M4.11 is
        the point. Phase M4.11 fails **closed** when a published agent version
        cannot be signed, because an unsigned version is an integrity hole in
        something ACT executes. An evidence bundle is a read-only report: an
        auditor who receives it unsigned — clearly labelled unsigned — is better
        served than one who receives nothing at all. What must never happen is
        an unsigned bundle presented as signed, which is why ``signed`` is
        returned explicitly and surfaced in the response rather than inferred
        from a null signature.
        """
        from app.runtime.versioning import canonical

        payload = canonical.canonicalize(document)
        digest = hashlib.sha256(payload).hexdigest()
        try:
            from app.core.config import settings
            from app.runtime.versioning.attestation import PAYLOAD_TYPE, pae
            from app.runtime.versioning.keys import SigningKeyService
            from app.runtime.versioning.signing.registry import get_signing_provider

            key = SigningKeyService(self.db).ensure_key(settings.SIGNING_DEFAULT_KEY_ID)
            result = get_signing_provider().sign(pae(PAYLOAD_TYPE, payload), key.key_id)
            envelope = {
                "payloadType": PAYLOAD_TYPE,
                "payload": base64.b64encode(payload).decode("ascii"),
                "signatures": [{
                    "keyid": f"{key.key_id}:{result.key_version}",
                    "sig": base64.b64encode(result.signature).decode("ascii"),
                }],
            }
            return payload, digest, envelope, key.key_id, True
        except Exception:  # noqa: BLE001 — see the docstring: unsigned-and-labelled beats nothing
            logger.warning("assurance: evidence bundle exported unsigned", exc_info=True)
            return payload, digest, None, None, False


# --------------------------------------------------------------------------- #
def summarize(rows) -> EvaluationSummary:
    return EvaluationSummary(
        evaluated=len(rows),
        passed=sum(1 for r in rows if r.result == "PASS"),
        failed=sum(1 for r in rows if r.result == "FAIL"),
        insufficient=sum(1 for r in rows if r.result == "INSUFFICIENT_EVIDENCE"),
        stale=sum(1 for r in rows if r.stale),
    )


def _eval_payload(row) -> dict:
    return {
        "control_id": row.control_id,
        "result": row.result,
        "reason": row.reason,
        "evidence": row.evidence,
        "evidence_as_of": row.evidence_as_of.isoformat() if row.evidence_as_of else None,
        "stale": row.stale,
        "remediation": row.remediation,
        "exception_reason": row.exception_reason,
        "catalog_version": row.catalog_version,
        "subject_id": str(row.subject_id) if row.subject_id else None,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


def _json_safe(value):
    """Evidence dicts come from control functions that read ORM rows, so a raw
    ``uuid.UUID`` or ``datetime`` can reach a JSONB column. Normalize once here
    rather than making every control remember."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value)
    return value


__all__ = ["AssuranceService", "EvaluationSummary", "summarize"]
