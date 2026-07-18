"""Identity Governance & Administration API (Phase 4.3.8 §19) — /api/v1/governance.

Certification campaign endpoints are a thin, permission-gated delegation to
the Phase 4.3.7 ``AccessReviewService`` (§5-§7 reuse it wholesale — see
app/governance/services.py docstring); everything else (SoD, toxic
permissions, privileged access, orphaned identities, risk scoring,
remediation, compliance reporting, the dashboard) is new in this module.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.authorization.admin.services import AccessReviewService
from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.core.database import get_db
from app.governance.schemas import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ComplianceFrameworkRead,
    ComplianceReportGenerate,
    ComplianceReportRead,
    FindingResolve,
    GovernanceAnalyticsRead,
    GovernanceDashboardRead,
    GovernanceFindingRead,
    GovernanceRiskScoreRead,
    OrphanedScanResult,
    PrivilegedAccountRead,
    RemediationActionCreate,
    RemediationActionRead,
    ReviewDecision,
    ReviewItemRead,
    SoDRuleCreate,
    SoDRuleRead,
    SoDRuleUpdate,
)
from app.governance.services import (
    ComplianceReportingService,
    GovernanceDashboardService,
    GovernanceFindingService,
    GovernanceRiskScoringService,
    OrphanedIdentityService,
    PrivilegedAccessReviewService,
    RemediationService,
    SoDAnalysisService,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.access_review import AccessReviewItem
from app.models.user import User

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])

_DASHBOARD = "governance.dashboard.view"
_CERT = "governance.certification.manage"
_SOD = "governance.sod.manage"
_SOD_VIEW = "governance.sod.view"
_TOXIC = "governance.toxic.manage"
_PRIVILEGED = "governance.privileged.manage"
_ORPHANED = "governance.orphaned.manage"
_FINDINGS = "governance.findings.manage"
_REMEDIATION = "governance.remediation.manage"
_COMPLIANCE = "governance.compliance.view"
_ANALYTICS = "governance.analytics.view"


# --------------------------------------------------------------------------- #
# Governance dashboard (§21)
# --------------------------------------------------------------------------- #
@router.get("/dashboard", response_model=GovernanceDashboardRead)
def dashboard(actor: User = Depends(require_permission(_DASHBOARD)), db: Session = Depends(get_db)):
    return GovernanceDashboardService(db).snapshot(actor)


@router.get("/analytics", response_model=GovernanceAnalyticsRead)
def analytics(actor: User = Depends(require_permission(_ANALYTICS)), db: Session = Depends(get_db)):
    return GovernanceDashboardService(db).analytics(actor)


# --------------------------------------------------------------------------- #
# Access certification campaigns (§5-§7, §19) — delegated to AccessReviewService
# --------------------------------------------------------------------------- #
def _campaign_read(svc: AccessReviewService, campaign) -> CampaignRead:
    total, decided, revoked = svc.counts(campaign.id)
    read = CampaignRead.model_validate(campaign)
    read.total_items, read.decided_items, read.revoked_items = total, decided, revoked
    return read


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(status_filter: str | None = Query(default=None, alias="status"),
                   actor: User = Depends(require_permission(_CERT)),
                   db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    return [_campaign_read(svc, c) for c in svc.list(actor, status=status_filter)]


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, actor: User = Depends(require_permission(_CERT)),
                    db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.create(actor, payload.model_dump(exclude_unset=True))
    AuthorizationAuditService(db).record_change(
        AuthorizationAuditEvent.CERTIFICATION_CREATED,
        organization_id=actor.organization_id, actor_id=actor.id,
        meta={"campaign_id": str(campaign.id), "campaign_type": campaign.campaign_type},
    )
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                 db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    return _campaign_read(svc, svc.get_or_404(actor, campaign_id))


@router.put("/campaigns/{campaign_id}", response_model=CampaignRead)
def update_campaign(campaign_id: uuid.UUID, payload: CampaignUpdate,
                    actor: User = Depends(require_permission(_CERT)), db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.update(actor, campaign_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return _campaign_read(svc, campaign)


@router.post("/campaigns/{campaign_id}/launch", response_model=CampaignRead)
def launch_campaign(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                    db: Session = Depends(get_db)):
    """§6 — "Campaign Created → Users Assigned → …"; launch snapshots scope."""
    svc = AccessReviewService(db)
    campaign = svc.get_or_404(actor, campaign_id)
    if campaign.status == "DRAFT":
        svc.schedule(actor, campaign_id)
    campaign = svc.activate(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/campaigns/{campaign_id}/items", response_model=list[ReviewItemRead])
def campaign_items(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                   db: Session = Depends(get_db)):
    return AccessReviewService(db).items(actor, campaign_id)


@router.post("/campaigns/{campaign_id}/complete", response_model=CampaignRead)
def complete_campaign(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                      db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.complete(actor, campaign_id)
    AuthorizationAuditService(db).record_change(
        AuthorizationAuditEvent.CERTIFICATION_COMPLETED,
        organization_id=actor.organization_id, actor_id=actor.id,
        meta={"campaign_id": str(campaign.id)},
    )
    db.commit()
    return _campaign_read(svc, campaign)


@router.post("/campaigns/{campaign_id}/archive", response_model=CampaignRead)
def archive_campaign(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                     db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.archive(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: uuid.UUID, actor: User = Depends(require_permission(_CERT)),
                    db: Session = Depends(get_db)) -> dict:
    report = AccessReviewService(db).export(actor, campaign_id)
    db.commit()
    return report


# --------------------------------------------------------------------------- #
# Reviews (§7, §19) — decide one item without knowing its campaign id
# --------------------------------------------------------------------------- #
def _locate_item(db: Session, actor: User, item_id: uuid.UUID) -> tuple[AccessReviewItem, uuid.UUID]:
    item = db.get(AccessReviewItem, item_id)
    if item is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "Review item not found.")
    campaign = AccessReviewService(db).get_or_404(actor, item.campaign_id)
    return item, campaign.id


def _decide(db: Session, actor: User, item_id: uuid.UUID, *, decision: str,
           payload: ReviewDecision, audit_event: AuthorizationAuditEvent) -> ReviewItemRead:
    item, campaign_id = _locate_item(db, actor, item_id)
    comment = payload.comment
    if decision == "DELEGATED" and payload.delegate_to is not None:
        comment = f"[delegated to {payload.delegate_to}] {comment or ''}".strip()
    decided = AccessReviewService(db).decide_item(
        actor, campaign_id, item_id, decision=decision, comment=comment)
    AuthorizationAuditService(db).record_change(
        audit_event, organization_id=actor.organization_id, actor_id=actor.id,
        identity_id=decided.subject_id,
        meta={"item_id": str(decided.id), "campaign_id": str(campaign_id), "decision": decision},
    )
    db.commit()
    return decided


@router.post("/reviews/{item_id}/approve", response_model=ReviewItemRead)
def approve_review(item_id: uuid.UUID, payload: ReviewDecision = ReviewDecision(),
                   actor: User = Depends(require_permission(_CERT)), db: Session = Depends(get_db)):
    return _decide(db, actor, item_id, decision="CERTIFIED", payload=payload,
                   audit_event=AuthorizationAuditEvent.ACCESS_APPROVED)


@router.post("/reviews/{item_id}/revoke", response_model=ReviewItemRead)
def revoke_review(item_id: uuid.UUID, payload: ReviewDecision = ReviewDecision(),
                  actor: User = Depends(require_permission(_CERT)), db: Session = Depends(get_db)):
    return _decide(db, actor, item_id, decision="REVOKED", payload=payload,
                   audit_event=AuthorizationAuditEvent.ACCESS_REVOKED)


@router.post("/reviews/{item_id}/delegate", response_model=ReviewItemRead)
def delegate_review(item_id: uuid.UUID, payload: ReviewDecision,
                    actor: User = Depends(require_permission(_CERT)), db: Session = Depends(get_db)):
    return _decide(db, actor, item_id, decision="DELEGATED", payload=payload,
                   audit_event=AuthorizationAuditEvent.ACCESS_REVIEW_ITEM_DECIDED)


@router.post("/reviews/{item_id}/modify", response_model=ReviewItemRead)
def modify_review(item_id: uuid.UUID, payload: ReviewDecision = ReviewDecision(),
                  actor: User = Depends(require_permission(_CERT)), db: Session = Depends(get_db)):
    return _decide(db, actor, item_id, decision="MODIFIED", payload=payload,
                   audit_event=AuthorizationAuditEvent.ACCESS_REVIEW_ITEM_DECIDED)


# --------------------------------------------------------------------------- #
# Separation of Duties (§9, §19)
# --------------------------------------------------------------------------- #
@router.get("/sod-rules", response_model=list[SoDRuleRead])
def list_sod_rules(status_filter: str | None = Query(default=None, alias="status"),
                   actor: User = Depends(require_permission(_SOD_VIEW)), db: Session = Depends(get_db)):
    return SoDAnalysisService(db).list_rules(actor, rule_type="SOD", status=status_filter)


@router.post("/sod-rules", response_model=SoDRuleRead, status_code=status.HTTP_201_CREATED)
def create_sod_rule(payload: SoDRuleCreate, actor: User = Depends(require_permission(_SOD)),
                    db: Session = Depends(get_db)):
    body = payload.model_dump()
    body["rule_type"] = "SOD"
    rule = SoDAnalysisService(db).create(actor, body)
    db.commit()
    return rule


@router.put("/sod-rules/{rule_id}", response_model=SoDRuleRead)
def update_sod_rule(rule_id: uuid.UUID, payload: SoDRuleUpdate,
                    actor: User = Depends(require_permission(_SOD)), db: Session = Depends(get_db)):
    rule = SoDAnalysisService(db).update(actor, rule_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return rule


@router.post("/sod-rules/{rule_id}/activate", response_model=SoDRuleRead)
def activate_sod_rule(rule_id: uuid.UUID, actor: User = Depends(require_permission(_SOD)),
                      db: Session = Depends(get_db)):
    rule = SoDAnalysisService(db).activate(actor, rule_id)
    db.commit()
    return rule


@router.post("/sod-rules/{rule_id}/disable", response_model=SoDRuleRead)
def disable_sod_rule(rule_id: uuid.UUID, actor: User = Depends(require_permission(_SOD)),
                     db: Session = Depends(get_db)):
    rule = SoDAnalysisService(db).disable(actor, rule_id)
    db.commit()
    return rule


@router.get("/sod-findings", response_model=list[GovernanceFindingRead])
def list_sod_findings(status_filter: str | None = Query(default=None, alias="status"),
                      actor: User = Depends(require_permission(_SOD_VIEW)), db: Session = Depends(get_db)):
    return GovernanceFindingService(db).list(actor, finding_type="SOD_VIOLATION", status=status_filter)


@router.post("/sod-findings/scan", response_model=list[GovernanceFindingRead])
def scan_sod(actor: User = Depends(require_permission(_SOD)), db: Session = Depends(get_db)):
    findings = SoDAnalysisService(db).analyze(actor)
    db.commit()
    return [f for f in findings if f.finding_type == "SOD_VIOLATION"]


# --------------------------------------------------------------------------- #
# Toxic permission detection (§10, §19) — same engine, rule_type=TOXIC_PERMISSION
# --------------------------------------------------------------------------- #
@router.get("/toxic-rules", response_model=list[SoDRuleRead])
def list_toxic_rules(status_filter: str | None = Query(default=None, alias="status"),
                     actor: User = Depends(require_permission(_SOD_VIEW)), db: Session = Depends(get_db)):
    return SoDAnalysisService(db).list_rules(actor, rule_type="TOXIC_PERMISSION", status=status_filter)


@router.post("/toxic-rules", response_model=SoDRuleRead, status_code=status.HTTP_201_CREATED)
def create_toxic_rule(payload: SoDRuleCreate, actor: User = Depends(require_permission(_TOXIC)),
                      db: Session = Depends(get_db)):
    body = payload.model_dump()
    body["rule_type"] = "TOXIC_PERMISSION"
    rule = SoDAnalysisService(db).create(actor, body)
    db.commit()
    return rule


@router.post("/toxic-rules/{rule_id}/activate", response_model=SoDRuleRead)
def activate_toxic_rule(rule_id: uuid.UUID, actor: User = Depends(require_permission(_TOXIC)),
                        db: Session = Depends(get_db)):
    rule = SoDAnalysisService(db).activate(actor, rule_id)
    db.commit()
    return rule


@router.post("/toxic-rules/{rule_id}/disable", response_model=SoDRuleRead)
def disable_toxic_rule(rule_id: uuid.UUID, actor: User = Depends(require_permission(_TOXIC)),
                       db: Session = Depends(get_db)):
    rule = SoDAnalysisService(db).disable(actor, rule_id)
    db.commit()
    return rule


@router.get("/toxic-findings", response_model=list[GovernanceFindingRead])
def list_toxic_findings(status_filter: str | None = Query(default=None, alias="status"),
                        actor: User = Depends(require_permission(_SOD_VIEW)), db: Session = Depends(get_db)):
    return GovernanceFindingService(db).list(actor, finding_type="TOXIC_PERMISSION", status=status_filter)


@router.post("/toxic-findings/scan", response_model=list[GovernanceFindingRead])
def scan_toxic(actor: User = Depends(require_permission(_TOXIC)), db: Session = Depends(get_db)):
    findings = SoDAnalysisService(db).analyze(actor)
    db.commit()
    return [f for f in findings if f.finding_type == "TOXIC_PERMISSION"]


# --------------------------------------------------------------------------- #
# Governance findings (§17, §19)
# --------------------------------------------------------------------------- #
@router.get("/findings", response_model=list[GovernanceFindingRead])
def list_findings(finding_type: str | None = Query(default=None),
                  status_filter: str | None = Query(default=None, alias="status"),
                  severity: str | None = Query(default=None),
                  actor: User = Depends(require_permission(_FINDINGS)), db: Session = Depends(get_db)):
    return GovernanceFindingService(db).list(actor, finding_type=finding_type,
                                             status=status_filter, severity=severity)


@router.post("/findings/{finding_id}/remediate", response_model=GovernanceFindingRead)
def remediate_finding(finding_id: uuid.UUID, payload: FindingResolve,
                      actor: User = Depends(require_permission(_FINDINGS)), db: Session = Depends(get_db)):
    finding = GovernanceFindingService(db).resolve(
        actor, finding_id, status=payload.status, comment=payload.comment)
    db.commit()
    return finding


# --------------------------------------------------------------------------- #
# Privileged access governance (§11, §19)
# --------------------------------------------------------------------------- #
@router.get("/privileged-accounts", response_model=list[PrivilegedAccountRead])
def list_privileged_accounts(actor: User = Depends(require_permission(_PRIVILEGED)),
                             db: Session = Depends(get_db)):
    accounts = PrivilegedAccessReviewService(db).list_accounts(actor)
    db.commit()  # persists any newly-computed risk score rows
    return accounts


@router.post("/privileged-accounts/reviews", status_code=status.HTTP_201_CREATED)
def request_privileged_review(identity_id: uuid.UUID, role_name: str,
                              assignment_id: uuid.UUID | None = None,
                              actor: User = Depends(require_permission(_PRIVILEGED)),
                              db: Session = Depends(get_db)) -> dict:
    # assignment_id is accepted (the SPA sends it, matching the shape of the
    # /decide call below) but not stored on the review — decide() takes it
    # again at decision time, which is when it's actually needed to enforce
    # a REVOKED verdict.
    review = PrivilegedAccessReviewService(db).request_review(
        actor, identity_id=identity_id, role_name=role_name)
    db.commit()
    return {"id": str(review.id), "status": review.status, "due_at": review.due_at}


@router.get("/privileged-accounts/reviews")
def list_privileged_reviews(status_filter: str | None = Query(default=None, alias="status"),
                            actor: User = Depends(require_permission(_PRIVILEGED)),
                            db: Session = Depends(get_db)) -> list[dict]:
    reviews = PrivilegedAccessReviewService(db).list_reviews(actor, status=status_filter)
    return [{
        "id": str(r.id), "identity_id": str(r.identity_id), "identity_label": r.identity_label,
        "role_name": r.role_name, "risk_score": r.risk_score, "status": r.status,
        "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None,
        "reviewed_at": r.reviewed_at, "due_at": r.due_at, "created_at": r.created_at,
    } for r in reviews]


@router.post("/privileged-accounts/reviews/{review_id}/decide")
def decide_privileged_review(review_id: uuid.UUID, decision: str, comment: str | None = None,
                             assignment_id: uuid.UUID | None = None,
                             actor: User = Depends(require_permission(_PRIVILEGED)),
                             db: Session = Depends(get_db)) -> dict:
    if decision not in ("APPROVED", "REVOKED"):
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "decision must be APPROVED or REVOKED.")
    review = PrivilegedAccessReviewService(db).decide(
        actor, review_id, decision=decision, comment=comment, assignment_id=assignment_id)
    db.commit()
    return {"id": str(review.id), "status": review.status}


# --------------------------------------------------------------------------- #
# Orphaned identity detection (§12, §19)
# --------------------------------------------------------------------------- #
@router.get("/orphaned-accounts", response_model=list[GovernanceFindingRead])
def list_orphaned_accounts(status_filter: str | None = Query(default=None, alias="status"),
                           actor: User = Depends(require_permission(_ORPHANED)),
                           db: Session = Depends(get_db)):
    return GovernanceFindingService(db).list(actor, finding_type="ORPHANED_ACCOUNT", status=status_filter)


@router.post("/orphaned-accounts/scan", response_model=OrphanedScanResult)
def scan_orphaned_accounts(actor: User = Depends(require_permission(_ORPHANED)), db: Session = Depends(get_db)):
    result = OrphanedIdentityService(db).scan(actor)
    db.commit()
    return result


# --------------------------------------------------------------------------- #
# Governance risk scoring (§13, §19)
# --------------------------------------------------------------------------- #
@router.get("/risk-scores", response_model=list[GovernanceRiskScoreRead])
def list_risk_scores(band: str | None = Query(default=None),
                     actor: User = Depends(require_permission(_ANALYTICS)), db: Session = Depends(get_db)):
    return GovernanceRiskScoringService(db).list(actor, band=band)


@router.post("/risk-scores/recalculate", response_model=list[GovernanceRiskScoreRead])
def recalculate_risk_scores(actor: User = Depends(require_permission(_ANALYTICS)), db: Session = Depends(get_db)):
    rows = GovernanceRiskScoringService(db).compute_all(actor)
    db.commit()
    return rows


# --------------------------------------------------------------------------- #
# Automated remediation (§14, §19)
# --------------------------------------------------------------------------- #
@router.get("/remediation-actions", response_model=list[RemediationActionRead])
def list_remediation_actions(status_filter: str | None = Query(default=None, alias="status"),
                             finding_id: uuid.UUID | None = Query(default=None),
                             actor: User = Depends(require_permission(_REMEDIATION)),
                             db: Session = Depends(get_db)):
    return RemediationService(db).list(actor, status=status_filter, finding_id=finding_id)


@router.post("/remediation-actions", response_model=RemediationActionRead, status_code=status.HTTP_201_CREATED)
def create_remediation_action(payload: RemediationActionCreate,
                              actor: User = Depends(require_permission(_REMEDIATION)),
                              db: Session = Depends(get_db)):
    action = RemediationService(db).create(actor, payload.model_dump())
    db.commit()
    return action


@router.post("/remediation-actions/{action_id}/execute", response_model=RemediationActionRead)
def execute_remediation_action(action_id: uuid.UUID, actor: User = Depends(require_permission(_REMEDIATION)),
                               db: Session = Depends(get_db)):
    action = RemediationService(db).execute(actor, action_id)
    db.commit()
    return action


# --------------------------------------------------------------------------- #
# Compliance reporting (§15, §16, §19, §22)
# --------------------------------------------------------------------------- #
@router.get("/compliance/frameworks", response_model=list[ComplianceFrameworkRead])
def compliance_frameworks(actor: User = Depends(require_permission(_COMPLIANCE)), db: Session = Depends(get_db)):
    return ComplianceReportingService(db).frameworks()


@router.get("/compliance/reports", response_model=list[ComplianceReportRead])
def list_compliance_reports(framework: str | None = Query(default=None),
                            actor: User = Depends(require_permission(_COMPLIANCE)),
                            db: Session = Depends(get_db)):
    return ComplianceReportingService(db).list(actor, framework=framework)


@router.post("/compliance/reports", response_model=ComplianceReportRead, status_code=status.HTTP_201_CREATED)
def generate_compliance_report(payload: ComplianceReportGenerate,
                               actor: User = Depends(require_permission(_COMPLIANCE)),
                               db: Session = Depends(get_db)):
    report = ComplianceReportingService(db).generate(
        actor, framework=payload.framework, report_type=payload.report_type, scope=payload.scope)
    db.commit()
    return report


@router.get("/compliance/reports/{report_id}")
def get_compliance_report(report_id: uuid.UUID, export_format: str = Query(default="json", alias="format"),
                          actor: User = Depends(require_permission(_COMPLIANCE)), db: Session = Depends(get_db)):
    """§22 — supports JSON (default) and CSV export. PDF/Excel are generated
    client-side from this payload, matching the export pattern already used by
    the audit and access-review exports in this codebase."""
    svc = ComplianceReportingService(db)
    report = svc.get_or_404(actor, report_id)
    if export_format == "csv":
        return PlainTextResponse(svc.to_csv(report), media_type="text/csv")
    return ComplianceReportRead.model_validate(report)
