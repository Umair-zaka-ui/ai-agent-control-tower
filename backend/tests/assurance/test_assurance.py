"""Phase 5.9 (M5.9) - Assurance, Evidence & Compliance.

The sharpest tests here are the two honesty proofs, and they are the reason the
phase exists:

  * **Absence is never a pass.** A control whose evidence has not been produced
    returns INSUFFICIENT_EVIDENCE, and a control that would otherwise pass on
    stale evidence returns INSUFFICIENT_EVIDENCE too — the database refuses to
    store a stale PASS at all. A compliance surface that reports "no findings"
    as "compliant" is the most dangerous false-green there is.

  * **No certification claim.** There is no ``compliant`` field, no status, no
    score and no coverage percentage anywhere in the model, the schemas or the
    responses. Asserted structurally, because a field that does not exist
    cannot be rendered as a badge.

AC-00..AC-17 + the §14 end-to-end proof; each AC has a named test.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.assurance import AssuranceEvaluation, AssuranceEvidenceBundle
from app.models.user import User
from app.runtime.registry.control import AgentProvenanceService

AS = "/api/v1/assurance"
_BACKEND = Path(__file__).resolve().parents[2]
_PKG = _BACKEND / "app" / "assurance"
_FRONTEND = _BACKEND.parent / "frontend"


def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(_PKG.glob("*.py")))


def _make_external(admin: dict, **kw) -> str:
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        agent = AgentProvenanceService(db).record_external_agent(
            actor, name=kw.pop("name", f"Shadow {uuid.uuid4().hex[:6]}"),
            origin_category=kw.pop("origin_category", "EXTERNAL"),
            origin_provider="LANGGRAPH", **kw)
        db.commit()
        return str(agent.id)
    finally:
        db.close()


def _make_native(client: TestClient, admin: dict) -> str:
    r = client.post("/api/v1/runtime/agents", headers=admin["headers"], json={
        "name": f"Native {uuid.uuid4().hex[:6]}", "description": "d",
        "business_purpose": "d", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "technical_owner_id": admin["user_id"], "compliance_owner_id": admin["user_id"],
        "definition": {"name": "D", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "a.h:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _evaluate(client: TestClient, admin: dict, agent_id: str) -> dict:
    r = client.post(f"{AS}/agents/{agent_id}/evaluate", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return {row["control_id"]: row for row in r.json()}


# --------------------------------------------------------------------------- #
# AC-00 - the frontend build is restored and guarded
# --------------------------------------------------------------------------- #
def test_ac00_the_frontend_build_defect_is_fixed() -> None:
    """Phase 0. The 4.9 defect was a type exported from its own module but never
    re-exported by the `@/services` barrel that `TraceDetailPage` imports it
    from — so `tsc -b` (and `npm run build`) failed while `vitest`, which does
    not typecheck, stayed green through four phases."""
    barrel = (_FRONTEND / "src" / "services" / "index.ts").read_text(encoding="utf-8")
    assert "export type { TraceContentResponse } from './observabilityService'" in barrel

    # And the guard that makes a recurrence loud rather than invisible exists.
    guard = _FRONTEND / "src" / "test" / "build-integrity.test.ts"
    assert guard.exists()
    src = guard.read_text(encoding="utf-8")
    assert "tsc" in src and "-b" in src


# --------------------------------------------------------------------------- #
# AC-01 - substrate
# --------------------------------------------------------------------------- #
def test_ac01_migration_head_and_evidence_sources_present() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.finops.budgets import BudgetService  # noqa: F401 - 4.4 cost evidence
    from app.models.graph import ControlGraphEdge  # noqa: F401 - 5.3 authority
    from app.models.posture import PostureFinding  # noqa: F401 - 5.5 findings
    from app.models.rbac import AuthorizationAudit  # noqa: F401 - the audit spine
    from app.models.runtime import AgentExecution  # noqa: F401 - 4.1/4.2 traces
    from app.models.threat import ThreatFinding  # noqa: F401 - 5.6 incidents

    # Deliberately NOT pinned to the global head. Phases 5.7 and 5.8 each pinned
    # it to their own migration, and both assertions broke the moment this phase
    # added one — a moving target by construction. The invariant that actually
    # matters is that this phase's migration is in the chain and the chain has a
    # single head; a later phase adding its own must not have to come back here.
    script = ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))
    assert len(script.get_heads()) == 1, "the migration chain must stay linear"
    revisions = {r.revision for r in script.walk_revisions()}
    assert "0061_assurance_evidence" in revisions


# --------------------------------------------------------------------------- #
# AC-02 / AC-06 - the control model, deterministic and evidence-naming
# --------------------------------------------------------------------------- #
def test_ac02_controls_declare_question_evidence_source_and_version() -> None:
    from app.assurance.controls import ASSURANCE_CATALOG_VERSION, CONTROLS

    assert CONTROLS, "the catalog must not be empty"
    for c in CONTROLS:
        assert c.question.endswith("?"), c.id
        assert c.evidence_source, c.id
        assert c.scope in ("AGENT", "ORGANIZATION")
        assert c.version
    assert ASSURANCE_CATALOG_VERSION


def test_ac06_evaluation_is_deterministic_and_names_its_evidence(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_native(client, admin)
    first = _evaluate(client, admin, agent_id)
    second = _evaluate(client, admin, agent_id)

    assert set(first) == set(second)
    for cid, row in first.items():
        assert row["result"] == second[cid]["result"], cid
        assert row["reason"], cid
        # A result that cannot name what it read is not reconstructable.
        assert isinstance(row["evidence"], dict), cid
        assert row["evidence"] != {} or row["result"] == "INSUFFICIENT_EVIDENCE", cid


def test_ac06_no_ml_or_scoring_in_the_catalog() -> None:
    """The 4.5 / 5.5 AST proof, applied here: a control is arithmetic over rows,
    not a model."""
    tree = ast.parse(_source())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("sklearn", "numpy", "scipy", "torch", "tensorflow", "pandas"):
        assert banned not in imported, banned


# --------------------------------------------------------------------------- #
# AC-03 - insufficient-evidence is first-class (THE headline)
# --------------------------------------------------------------------------- #
def test_ac03_absent_evidence_is_insufficient_never_pass(
        client: TestClient, admin: dict) -> None:
    """A fresh tenant has never run posture, so every posture-backed control
    must report that it cannot tell — not that all is well."""
    agent_id = _make_native(client, admin)
    results = _evaluate(client, admin, agent_id)

    posture_backed = results["ACT.GOVERNANCE.POLICY_COVERAGE"]
    assert posture_backed["result"] == "INSUFFICIENT_EVIDENCE"
    assert posture_backed["result"] != "PASS"
    assert "never been evaluated" in posture_backed["reason"]
    # It names the absence rather than merely shrugging.
    assert posture_backed["evidence"]["posture_evaluations"] == 0


def test_ac03_a_conclusive_negative_is_fail_not_insufficient(
        client: TestClient, admin: dict) -> None:
    """The mirror failure. An agent row with no owner is not *missing*
    evidence — the row is the evidence and it is conclusive. Reporting that as
    "cannot tell" would hide a real finding behind a shrug."""
    agent_id = _make_external(admin)  # discovered, unowned
    results = _evaluate(client, admin, agent_id)

    owner = results["ACT.OWNERSHIP.ACCOUNTABLE_OWNER"]
    assert owner["result"] == "FAIL"
    assert owner["evidence"]["owner_id"] is None
    assert owner["evidence"]["source"] == "agents.owner_id"


def test_ac03_unknowable_is_insufficient_not_fail(
        client: TestClient, admin: dict) -> None:
    """And the other side of that line: an agent ACT does not run has no
    executions, so its traceability is genuinely unknowable. Calling that FAIL
    would invent a violation."""
    agent_id = _make_external(admin)
    results = _evaluate(client, admin, agent_id)

    trace = results["ACT.RUNTIME.TRACEABLE"]
    assert trace["result"] == "INSUFFICIENT_EVIDENCE"
    assert trace["evidence"]["executions"] == 0
    assert "cannot see what it does not run" in trace["reason"]


def test_ac03_stale_evidence_never_passes_and_the_database_enforces_it(
        client: TestClient, admin: dict) -> None:
    """Belt and braces: the evaluator downgrades a stale pass, and the schema
    refuses to store one even if some future caller tried."""
    agent_id = _make_native(client, admin)
    _evaluate(client, admin, agent_id)

    db = SessionLocal()
    try:
        row = db.execute(select(AssuranceEvaluation).where(
            AssuranceEvaluation.subject_id == uuid.UUID(agent_id)).limit(1)).scalars().one()
        with pytest.raises(Exception):
            db.execute(text(
                "UPDATE assurance_evaluations SET result='PASS', stale=true WHERE id=:i"),
                {"i": str(row.id)})
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_ac03_a_stale_posture_run_downgrades_the_pass(
        client: TestClient, admin: dict) -> None:
    """Evidence older than the freshness policy is reported insufficient and
    flagged stale — "we checked six weeks ago" does not substantiate a claim
    about today."""
    from app.assurance.service import AssuranceService
    from app.posture.evaluator import PostureEvaluator

    agent_id = _make_native(client, admin)
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        PostureEvaluator(db).evaluate_tenant(actor)
        agent = db.get(Agent, uuid.UUID(agent_id))
        # Same evidence, an intolerant freshness policy: what passed a moment
        # ago must now read as insufficient, not as a pass.
        rows = AssuranceService(db).evaluate_agent(actor, agent, freshness_days=0)
        posture_rows = [r for r in rows if r.control_id == "ACT.RELIABILITY.SLO_COVERAGE"]
        assert posture_rows
        row = posture_rows[0]
        assert row.result == "INSUFFICIENT_EVIDENCE"
        assert row.stale is True
        assert row.evidence_as_of is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-04 - no certification / compliance-status claim (structural)
# --------------------------------------------------------------------------- #
def test_ac04_no_compliant_status_field_exists_anywhere() -> None:
    """A badge cannot be rendered from a field that does not exist."""
    for model in (AssuranceEvaluation, AssuranceEvidenceBundle):
        cols = {c.name for c in model.__table__.columns}
        for banned in ("compliant", "compliance_status", "status", "score",
                       "coverage", "coverage_percent", "certified", "verdict",
                       "grade", "rating"):
            assert banned not in cols, f"{model.__tablename__}.{banned}"

    from app.assurance import schemas

    for name in dir(schemas):
        fields = getattr(getattr(schemas, name), "model_fields", None)
        if not fields:
            continue
        for banned in ("compliant", "compliance_status", "score", "coverage",
                       "certified", "verdict"):
            assert banned not in fields, f"{name}.{banned}"


def test_ac04_results_admit_no_compliant_value() -> None:
    from app.assurance.controls import RESULTS
    from app.models.assurance import ASSURANCE_RESULTS

    assert set(RESULTS) == {"PASS", "FAIL", "INSUFFICIENT_EVIDENCE"}
    assert set(ASSURANCE_RESULTS) == set(RESULTS)


def test_ac04_framework_report_carries_its_disclaimer_and_no_aggregate(
        client: TestClient, admin: dict) -> None:
    """The caveat travels with the data, not as a UI label someone can drop."""
    r = client.get(f"{AS}/frameworks/NIST_AI_RMF", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert "not a compliance determination" in body["disclaimer"]
    assert "certification" in body["disclaimer"]
    assert body["framework"]["scope_note"]
    # No framework-level aggregate of any kind.
    for banned in ("score", "coverage", "compliant", "status", "percentage", "verdict"):
        assert banned not in body, banned


def test_ac04_mappings_are_relevance_claims_not_compliance_claims() -> None:
    from app.assurance.frameworks import FRAMEWORKS, MAPPINGS

    for m in MAPPINGS:
        assert m.rationale, m.control_ref
        assert m.act_control_ids, m.control_ref
    for f in FRAMEWORKS:
        # Each framework states in its own data what the mapping is not.
        assert "no" in f.scope_note.lower()
        assert f.revision


# --------------------------------------------------------------------------- #
# AC-05 - the per-agent assurance answers over real evidence
# --------------------------------------------------------------------------- #
def test_ac05_the_assurance_questions_are_all_answered(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_native(client, admin)
    results = _evaluate(client, admin, agent_id)

    for expected in ("ACT.OWNERSHIP.ACCOUNTABLE_OWNER", "ACT.PROVENANCE.KNOWN_ORIGIN",
                     "ACT.GOVERNANCE.POLICY_COVERAGE", "ACT.RELIABILITY.SLO_COVERAGE",
                     "ACT.CREDENTIAL.LIFECYCLE", "ACT.SUPPLY_CHAIN.MCP_TRUST",
                     "ACT.TOOL.LEAST_PRIVILEGE", "ACT.MODEL.APPROVED",
                     "ACT.RUNTIME.TRACEABLE", "ACT.COST.GOVERNED",
                     "ACT.AUTHORITY.CHAIN_PROVABLE", "ACT.INCIDENT.RECONSTRUCTABLE"):
        assert expected in results, expected
        assert results[expected]["result"] in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")


def test_ac05_an_owned_agent_passes_the_owner_control_with_its_evidence(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_native(client, admin)
    owner = _evaluate(client, admin, agent_id)["ACT.OWNERSHIP.ACCOUNTABLE_OWNER"]
    assert owner["result"] == "PASS"
    assert owner["evidence"]["owner_id"] == admin["user_id"]


# --------------------------------------------------------------------------- #
# AC-07 - freshness and exceptions
# --------------------------------------------------------------------------- #
def test_ac07_an_exception_documents_but_never_flips_the_result(
        client: TestClient, admin: dict) -> None:
    """A FAIL with an accepted risk still reads FAIL. An exception that turned
    it green would be indistinguishable from the control actually being met."""
    agent_id = _make_external(admin)
    _evaluate(client, admin, agent_id)

    db = SessionLocal()
    try:
        row = db.execute(select(AssuranceEvaluation).where(
            AssuranceEvaluation.subject_id == uuid.UUID(agent_id),
            AssuranceEvaluation.control_id == "ACT.OWNERSHIP.ACCOUNTABLE_OWNER",
        )).scalars().one()
        eval_id, before = str(row.id), row.result
    finally:
        db.close()

    r = client.post(f"{AS}/evaluations/{eval_id}/exception", headers=admin["headers"],
                    json={"reason": "Decommissioned next quarter; risk accepted by CISO."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == before == "FAIL"
    assert "risk accepted" in body["exception_reason"]
    assert body["exception_at"]


def test_ac07_an_exception_is_audited_not_silent(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_external(admin)
    _evaluate(client, admin, agent_id)
    db = SessionLocal()
    try:
        row = db.execute(select(AssuranceEvaluation).where(
            AssuranceEvaluation.subject_id == uuid.UUID(agent_id)).limit(1)).scalars().one()
        eval_id = str(row.id)
    finally:
        db.close()
    client.post(f"{AS}/evaluations/{eval_id}/exception", headers=admin["headers"],
                json={"reason": "accepted"})
    assert "ASSURANCE_EXCEPTION_RECORDED" in _audit_events(admin["organization_id"])


def test_ac07_an_exception_survives_re_evaluation(
        client: TestClient, admin: dict) -> None:
    """A routine re-run must not silently discard a human decision."""
    agent_id = _make_external(admin)
    _evaluate(client, admin, agent_id)
    db = SessionLocal()
    try:
        row = db.execute(select(AssuranceEvaluation).where(
            AssuranceEvaluation.subject_id == uuid.UUID(agent_id),
            AssuranceEvaluation.control_id == "ACT.OWNERSHIP.ACCOUNTABLE_OWNER",
        )).scalars().one()
        eval_id = str(row.id)
    finally:
        db.close()
    client.post(f"{AS}/evaluations/{eval_id}/exception", headers=admin["headers"],
                json={"reason": "carried over"})

    after = _evaluate(client, admin, agent_id)["ACT.OWNERSHIP.ACCOUNTABLE_OWNER"]
    assert after["exception_reason"] == "carried over"


def _audit_events(organization_id: str) -> set[str]:
    db = SessionLocal()
    try:
        return set(db.execute(text(
            "SELECT event_type FROM authorization_audit WHERE organization_id = :o"),
            {"o": organization_id}).scalars())
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# AC-08 - evidence export
# --------------------------------------------------------------------------- #
def test_ac08_export_is_tenant_scoped_signed_and_audited(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_native(client, admin)
    _evaluate(client, admin, agent_id)

    r = client.post(f"{AS}/export", headers=admin["headers"], params={"framework_id": "SOC2"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["content_digest"]
    assert body["document"]["organization_id"] == admin["organization_id"]
    assert body["document"]["evaluations"]
    # Tamper-evidence is stated in words, never inferred from a null signature.
    assert body["tamper_evidence"]
    if body["signed"]:
        assert body["signature"]["payloadType"]
        assert body["signature"]["signatures"][0]["sig"]
        assert "DSSE" in body["tamper_evidence"]
    else:
        assert "UNSIGNED" in body["tamper_evidence"]

    assert "ASSURANCE_EVIDENCE_EXPORTED" in _audit_events(admin["organization_id"])


def test_ac08_export_requires_the_distinct_stronger_permission(
        client: TestClient, admin: dict) -> None:
    from tests.assurance.conftest import PASSWORD

    email = f"asv_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD,
        "role": "VIEWER", "organization_id": admin["organization_id"]})
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    viewer = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.post(f"{AS}/export", headers=viewer).status_code == 403


def test_ac08_export_permission_is_never_implied_by_view_or_manage() -> None:
    from app.services.rbac_service import PERMISSION_CATALOG, SYSTEM_ROLE_PERMISSIONS

    for code in ("assurance.view", "assurance.manage", "assurance.export"):
        assert code in PERMISSION_CATALOG, code
    assert "assurance.export" not in SYSTEM_ROLE_PERMISSIONS["VIEWER"]
    assert "assurance.export" not in SYSTEM_ROLE_PERMISSIONS["REVIEWER"]


def test_ac08_no_secret_appears_in_a_bundle(client: TestClient, admin: dict) -> None:
    import json as jsonlib

    agent_id = _make_native(client, admin)
    _evaluate(client, admin, agent_id)
    body = client.post(f"{AS}/export", headers=admin["headers"]).json()
    blob = jsonlib.dumps(body["document"])

    for banned in ("key_hash", "secret", "password", "token", "ciphertext",
                   "private_key", "api_key"):
        assert banned not in blob.lower(), banned


# --------------------------------------------------------------------------- #
# AC-09 - maps existing evidence; creates none
# --------------------------------------------------------------------------- #
def test_ac09_no_new_evidence_source_or_audit_system() -> None:
    src = _source()
    tree = ast.parse(src)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

    # It reuses the one audit service; it does not define a second.
    assert "AuthorizationAuditService" in src
    assert "class AuditService" not in src
    assert "__tablename__" not in src  # models live in app/models/assurance.py only

    # And it never writes into another domain's evidence tables.
    for banned in ("activate", "revoke", "suspend", "terminate", "contain"):
        assert banned not in called, banned


def test_ac09_control_definitions_live_in_versioned_code_not_a_table() -> None:
    """A mapping from ACT evidence to a published control is logic to review in
    a diff, not data an operator can edit into claiming something ACT cannot
    substantiate."""
    from app.core.database import Base

    names = set(Base.metadata.tables)
    for banned in ("assurance_controls", "assurance_frameworks",
                   "assurance_control_definitions", "framework_mappings"):
        assert banned not in names, banned

    from app.assurance.controls import ASSURANCE_CATALOG_VERSION
    from app.assurance.frameworks import MAPPING_VERSION

    assert ASSURANCE_CATALOG_VERSION and MAPPING_VERSION


# --------------------------------------------------------------------------- #
# AC-10 - idempotent + 3.8-schedulable
# --------------------------------------------------------------------------- #
def test_ac10_evaluation_is_idempotent_and_does_not_accumulate(
        client: TestClient, admin: dict) -> None:
    agent_id = _make_native(client, admin)
    _evaluate(client, admin, agent_id)
    _evaluate(client, admin, agent_id)
    _evaluate(client, admin, agent_id)

    db = SessionLocal()
    try:
        rows = db.execute(select(AssuranceEvaluation).where(
            AssuranceEvaluation.subject_id == uuid.UUID(agent_id))).scalars().all()
        control_ids = [r.control_id for r in rows]
        assert len(control_ids) == len(set(control_ids)), "results must replace, not accumulate"
    finally:
        db.close()


def test_ac10_is_a_registered_scheduler_handler_with_no_new_scheduler() -> None:
    import app.scheduler.handlers as handlers

    assert "assurance.evaluate" in handlers.registered_keys()
    assert not (_PKG / "scheduler.py").exists()
    assert "BackgroundScheduler" not in _source()


# --------------------------------------------------------------------------- #
# AC-11 - tenant isolation
# --------------------------------------------------------------------------- #
def test_ac11_cross_tenant_subject_is_404(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    foreign = _make_external(other_org_admin)
    assert client.post(f"{AS}/agents/{foreign}/evaluate",
                       headers=admin["headers"]).status_code == 404
    assert client.post(f"{AS}/export", headers=admin["headers"],
                       params={"subject_id": foreign}).status_code == 404


def test_ac11_a_bundle_never_contains_another_tenants_evidence(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    mine = _make_native(client, admin)
    theirs = _make_native(client, other_org_admin)
    _evaluate(client, admin, mine)
    _evaluate(client, other_org_admin, theirs)

    body = client.post(f"{AS}/export", headers=admin["headers"]).json()
    subjects = {e["subject_id"] for e in body["document"]["evaluations"]}
    assert theirs not in subjects
    assert mine in subjects
    assert body["document"]["organization_id"] == admin["organization_id"]


def test_ac11_evaluations_list_is_tenant_scoped(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    theirs = _make_native(client, other_org_admin)
    _evaluate(client, other_org_admin, theirs)
    rows = client.get(f"{AS}/evaluations", headers=admin["headers"]).json()
    assert all(r["subject_id"] != theirs for r in rows)


# --------------------------------------------------------------------------- #
# AC-12 - truthful failure
# --------------------------------------------------------------------------- #
def test_ac12_an_unknown_framework_is_404_not_an_empty_report(
        client: TestClient, admin: dict) -> None:
    r = client.get(f"{AS}/frameworks/NOT_A_FRAMEWORK", headers=admin["headers"])
    assert r.status_code == 404


def test_ac12_a_framework_control_with_no_evidence_says_so(
        client: TestClient, admin: dict) -> None:
    """An unevaluated tenant's framework report shows controls with no evidence
    available — not controls quietly reported as satisfied."""
    body = client.get(f"{AS}/frameworks/SOC2", headers=admin["headers"]).json()
    for control in body["controls"]:
        if not control["evidence_available"]:
            assert control["evaluations"] == []
            assert control["counts"]["passed"] == 0


# --------------------------------------------------------------------------- #
# AC-14 - the migration
# --------------------------------------------------------------------------- #
def test_ac14_migration_is_additive_and_reversible() -> None:
    path = _BACKEND / "migrations" / "versions" / "0061_assurance_evidence.py"
    src = path.read_text(encoding="utf-8")
    assert 'down_revision = "0060_external_gov_bridge"' in src
    assert len("0061_assurance_evidence") <= 32
    upgrade = src.split("def upgrade")[1].split("def downgrade")[0]
    for destructive in ("drop_table", "drop_column", "alter_column"):
        assert destructive not in upgrade, destructive
    downgrade = src.split("def downgrade")[1]
    for table in ("assurance_evidence_bundles", "assurance_evaluations"):
        assert f'drop_table("{table}")' in downgrade


def test_ac14_evaluations_reference_evidence_rows() -> None:
    fks = {fk.target_fullname for c in AssuranceEvaluation.__table__.columns
           for fk in c.foreign_keys}
    assert "agents.id" in fks
    assert "organizations.id" in fks


# --------------------------------------------------------------------------- #
# AC-17 - hygiene
# --------------------------------------------------------------------------- #
def test_ac17_no_todo_fixme_skip_or_xfail_in_this_phase() -> None:
    targets = list(_PKG.glob("*.py")) + [
        _BACKEND / "app" / "models" / "assurance.py",
        _BACKEND / "migrations" / "versions" / "0061_assurance_evidence.py",
        Path(__file__),
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        body = src.split("def test_ac17")[0] if path == Path(__file__) else src
        for marker in ("TODO", "FIXME", "NotImplementedError",
                       "pytest.mark.skip", "pytest.mark.xfail"):
            assert marker not in body, f"{path.name}: {marker}"


# --------------------------------------------------------------------------- #
# §14 - the end-to-end proof
# --------------------------------------------------------------------------- #
def test_e2e_assurance_over_a_real_estate_reports_evidence_not_a_verdict(
        client: TestClient, admin: dict) -> None:
    """Over a real estate — a governed native agent and a discovered shadow one —
    assurance evaluates a framework mapping against real evidence.

    The governed agent's evidenced controls PASS, each naming what it read. The
    shadow agent's owner and provenance controls FAIL or report insufficient,
    each naming the absence — never a pass. A control whose evidence source has
    produced nothing reports INSUFFICIENT_EVIDENCE. A bundle exports, scoped and
    audited. And nowhere in any of it is there a compliance verdict.
    """
    from app.posture.evaluator import PostureEvaluator

    native = _make_native(client, admin)
    shadow = _make_external(admin, name="Shadow Copilot", origin_category="UNKNOWN")

    # Real posture evidence, produced by 5.5's own evaluator.
    db = SessionLocal()
    try:
        PostureEvaluator(db).evaluate_tenant(db.get(User, uuid.UUID(admin["user_id"])))
    finally:
        db.close()

    native_results = _evaluate(client, admin, native)
    shadow_results = _evaluate(client, admin, shadow)

    # 1. The governed agent: an owner, evidenced.
    owner = native_results["ACT.OWNERSHIP.ACCOUNTABLE_OWNER"]
    assert owner["result"] == "PASS"
    assert owner["evidence"]["owner_id"] == admin["user_id"]

    # 2. The shadow agent: unowned and of unknown origin — both FAIL, both
    #    naming the absence. Never a pass.
    assert shadow_results["ACT.OWNERSHIP.ACCOUNTABLE_OWNER"]["result"] == "FAIL"
    provenance = shadow_results["ACT.PROVENANCE.KNOWN_ORIGIN"]
    assert provenance["result"] == "FAIL"
    assert provenance["evidence"]["origin_category"] == "UNKNOWN"

    # 3. A source that has produced nothing: insufficient, not pass.
    trace = shadow_results["ACT.RUNTIME.TRACEABLE"]
    assert trace["result"] == "INSUFFICIENT_EVIDENCE"
    assert trace["evidence"]["executions"] == 0

    # 4. Every result is one of the three; none is a verdict.
    for results in (native_results, shadow_results):
        for cid, row in results.items():
            assert row["result"] in ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE"), cid

    # 5. The framework report maps evidence and disclaims a verdict.
    report = client.get(f"{AS}/frameworks/ISO_42001", headers=admin["headers"]).json()
    assert report["controls"]
    assert "not a compliance determination" in report["disclaimer"]
    assert "score" not in report and "compliant" not in report

    # 6. A bundle exports, tenant-scoped and audited.
    bundle = client.post(f"{AS}/export", headers=admin["headers"],
                         params={"framework_id": "ISO_42001"}).json()
    assert bundle["document"]["organization_id"] == admin["organization_id"]
    assert bundle["content_digest"]
    assert "no compliance determination" in bundle["document"]["disclaimer"]

    db = SessionLocal()
    try:
        recorded = db.execute(select(AssuranceEvidenceBundle).where(
            AssuranceEvidenceBundle.organization_id == uuid.UUID(admin["organization_id"]))
        ).scalars().all()
        assert recorded
        assert all(b.content_digest for b in recorded)
    finally:
        db.close()

    events = _audit_events(admin["organization_id"])
    assert {"ASSURANCE_EVALUATED", "ASSURANCE_EVIDENCE_EXPORTED"} <= events
