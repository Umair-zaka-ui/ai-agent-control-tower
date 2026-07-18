"""Identity Governance & Administration services (Phase 4.3.8).

Certification campaigns (§5-§7) are not re-implemented here: they delegate to
the Phase 4.3.7 ``AccessReviewService`` — the same lifecycle, enforcement and
audit trail, extended with a ``campaign_type`` and free-form decision values
(MODIFIED/DELEGATED alongside CERTIFIED/REVOKED) so this module never forks
that engine.

Every other service is tenant-scoped to the acting administrator's
organization and records its changes through ``AuthorizationAuditService``,
matching the rest of the authorization domain.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService, RoleAssignmentService, RoleHierarchyService
from app.core.enums import ApiKeyStatus
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.session import UserSession
from app.models.access_review import AccessReviewCampaign, AccessReviewItem
from app.models.agent import Agent
from app.models.api_key import AgentApiKey
from app.models.approval import Approval
from app.models.governance import (
    ComplianceReport,
    GovernanceFinding,
    GovernanceRiskScore,
    PrivilegedAccountReview,
    RemediationAction,
    SoDRule,
)
from app.models.organization_hierarchy import Delegation
from app.models.rbac import Role, UserRole
from app.models.user import User

# Tracked privileged roles (§11). Service accounts are a distinct identity
# type from ``User`` in this codebase and are not yet covered — see
# docs/governance/privileged-access.md.
PRIVILEGED_ROLE_NAMES: frozenset[str] = frozenset({
    "ROLE_PLATFORM_OWNER", "ROLE_PLATFORM_ADMIN", "ROLE_SECURITY_ADMIN",
    "ROLE_ORG_ADMIN", "ROLE_COMPLIANCE_ADMIN", "SUPER_ADMIN", "ADMIN",
})

INACTIVITY_THRESHOLD_DAYS = 90
_RISK_BANDS = ((81, "CRITICAL"), (51, "HIGH"), (21, "MEDIUM"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _band_for(score: int) -> str:
    for floor, band in _RISK_BANDS:
        if score >= floor:
            return band
    return "LOW"


def _user_permission_codes(db: Session, user_id: uuid.UUID,
                           *, role_cache: dict[uuid.UUID, set[str]] | None = None) -> set[str]:
    """Union of effective permission codes across a user's active, non-expired,
    non-deleted role assignments (role hierarchy inheritance included).

    ``role_cache`` memoizes ``resolve_effective_permissions`` by role id across
    a whole scan: an org's users typically share a small set of common roles,
    so without it a bulk scan (§10 ``analyze``) re-walks the same role
    hierarchy once per user instead of once per distinct role."""
    now = _now()
    role_ids = set(db.execute(
        select(UserRole.role_id).join(Role, Role.id == UserRole.role_id).where(
            UserRole.user_id == user_id,
            Role.status.notin_(["DELETED", "ARCHIVED"]),
            (UserRole.expires_at.is_(None)) | (UserRole.expires_at > now),
        )
    ).scalars())
    if not role_ids:
        return set()
    hierarchy = RoleHierarchyService(db)
    codes: set[str] = set()
    for role_id in role_ids:
        if role_cache is not None and role_id in role_cache:
            codes |= role_cache[role_id]
            continue
        resolved = hierarchy.resolve_effective_permissions(role_id)
        if role_cache is not None:
            role_cache[role_id] = resolved
        codes |= resolved
    return codes


# --------------------------------------------------------------------------- #
# SoD / toxic-permission rules + detection (§9, §10)
# --------------------------------------------------------------------------- #
class SoDAnalysisService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def get_or_404(self, actor: User, rule_id: uuid.UUID) -> SoDRule:
        rule = self.db.get(SoDRule, rule_id)
        if rule is None or rule.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.SOD_RULE_NOT_FOUND, "Rule not found.")
        return rule

    def list_rules(self, actor: User, *, rule_type: str | None = None,
                   status: str | None = None) -> list[SoDRule]:
        stmt = select(SoDRule).where(SoDRule.organization_id == actor.organization_id)
        if rule_type:
            stmt = stmt.where(SoDRule.rule_type == rule_type)
        if status:
            stmt = stmt.where(SoDRule.status == status)
        return list(self.db.execute(stmt.order_by(SoDRule.created_at.desc())).scalars())

    def create(self, actor: User, payload: dict) -> SoDRule:
        rule = SoDRule(organization_id=actor.organization_id, created_by=actor.id, **payload)
        self.db.add(rule)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.SOD_RULE_CREATED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"rule_id": str(rule.id), "name": rule.name, "rule_type": rule.rule_type},
        )
        return rule

    def update(self, actor: User, rule_id: uuid.UUID, payload: dict) -> SoDRule:
        rule = self.get_or_404(actor, rule_id)
        if rule.status == "ACTIVE":
            raise IdentityError(ErrorCode.SOD_RULE_NOT_ACTIVE,
                                "Disable the rule before editing an active one.")
        for key, value in payload.items():
            if value is not None:
                setattr(rule, key, value)
        rule.updated_at = _now()
        self.db.flush()
        return rule

    def activate(self, actor: User, rule_id: uuid.UUID) -> SoDRule:
        """§24 — SoD/toxic rules require approval before activation."""
        rule = self.get_or_404(actor, rule_id)
        rule.status = "ACTIVE"
        rule.approved_by = actor.id
        rule.approved_at = _now()
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.SOD_RULE_ACTIVATED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"rule_id": str(rule.id)},
        )
        return rule

    def disable(self, actor: User, rule_id: uuid.UUID) -> SoDRule:
        rule = self.get_or_404(actor, rule_id)
        rule.status = "DISABLED"
        self.db.flush()
        return rule

    def _open_finding_keys(self, organization_id: uuid.UUID) -> set[tuple]:
        rows = self.db.execute(
            select(GovernanceFinding.identity_id, GovernanceFinding.rule_id).where(
                GovernanceFinding.organization_id == organization_id,
                GovernanceFinding.status == "OPEN",
                GovernanceFinding.finding_type.in_(("SOD_VIOLATION", "TOXIC_PERMISSION")),
            )
        ).all()
        return {(identity_id, rule_id) for identity_id, rule_id in rows}

    def _evaluate(self, user: User, rules: list[SoDRule], seen: set[tuple],
                  *, organization_id: uuid.UUID, actor_id: uuid.UUID | None,
                  role_cache: dict[uuid.UUID, set[str]] | None = None) -> list[GovernanceFinding]:
        codes = _user_permission_codes(self.db, user.id, role_cache=role_cache)
        if not codes:
            return []
        created: list[GovernanceFinding] = []
        for rule in rules:
            key = (user.id, rule.id)
            if key in seen:
                continue
            matched_a = sorted(set(rule.permissions_a) & codes)
            matched_b = sorted(set(rule.permissions_b) & codes)
            if not (matched_a and matched_b):
                continue
            finding_type = "TOXIC_PERMISSION" if rule.rule_type == "TOXIC_PERMISSION" else "SOD_VIOLATION"
            finding = GovernanceFinding(
                organization_id=organization_id, finding_type=finding_type,
                severity=rule.risk_level, identity_id=user.id, identity_label=user.email,
                rule_id=rule.id,
                details={"rule_name": rule.name, "matched_a": matched_a, "matched_b": matched_b},
            )
            self.db.add(finding)
            self.db.flush()
            seen.add(key)
            created.append(finding)
            event = (AuthorizationAuditEvent.TOXIC_PERMISSION_FOUND if rule.rule_type == "TOXIC_PERMISSION"
                     else AuthorizationAuditEvent.SOD_VIOLATION_FOUND)
            self.audit.record_change(
                event, organization_id=organization_id, actor_id=actor_id, identity_id=user.id,
                meta={"rule_id": str(rule.id), "finding_id": str(finding.id)},
            )
        return created

    def analyze(self, actor: User) -> list[GovernanceFinding]:
        """Org-wide scan (§10: "detection runs continuously") — every active user
        against every ACTIVE rule."""
        rules = self.list_rules(actor, status="ACTIVE")
        if not rules:
            return []
        users = list(self.db.execute(
            select(User).where(User.organization_id == actor.organization_id, User.is_active.is_(True))
        ).scalars())
        seen = self._open_finding_keys(actor.organization_id)
        role_cache: dict[uuid.UUID, set[str]] = {}
        created: list[GovernanceFinding] = []
        for user in users:
            created.extend(self._evaluate(user, rules, seen,
                                          organization_id=actor.organization_id, actor_id=actor.id,
                                          role_cache=role_cache))
        return created

    def scan_identity(self, user: User, *, organization_id: uuid.UUID,
                      actor_id: uuid.UUID | None) -> list[GovernanceFinding]:
        """§10 — best-effort scan of one identity, called after a role
        assignment changes. Never raises: a scan failure must not block the
        assignment it observes."""
        rules = self.list_rules_for_org(organization_id)
        if not rules:
            return []
        seen = self._open_finding_keys(organization_id)
        return self._evaluate(user, rules, seen, organization_id=organization_id, actor_id=actor_id)

    def list_rules_for_org(self, organization_id: uuid.UUID) -> list[SoDRule]:
        return list(self.db.execute(
            select(SoDRule).where(SoDRule.organization_id == organization_id, SoDRule.status == "ACTIVE")
        ).scalars())


# --------------------------------------------------------------------------- #
# Governance findings (§17)
# --------------------------------------------------------------------------- #
class GovernanceFindingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def get_or_404(self, actor: User, finding_id: uuid.UUID) -> GovernanceFinding:
        finding = self.db.get(GovernanceFinding, finding_id)
        if finding is None or finding.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.GOVERNANCE_FINDING_NOT_FOUND, "Finding not found.")
        return finding

    def list(self, actor: User, *, finding_type: str | None = None, status: str | None = None,
             severity: str | None = None) -> list[GovernanceFinding]:
        stmt = select(GovernanceFinding).where(GovernanceFinding.organization_id == actor.organization_id)
        if finding_type:
            stmt = stmt.where(GovernanceFinding.finding_type == finding_type)
        if status:
            stmt = stmt.where(GovernanceFinding.status == status)
        if severity:
            stmt = stmt.where(GovernanceFinding.severity == severity)
        return list(self.db.execute(stmt.order_by(GovernanceFinding.detected_at.desc())).scalars())

    def resolve(self, actor: User, finding_id: uuid.UUID, *, status: str,
               comment: str | None = None) -> GovernanceFinding:
        finding = self.get_or_404(actor, finding_id)
        finding.status = status
        finding.resolved_by = actor.id
        finding.resolved_at = _now() if status in ("REMEDIATED", "DISMISSED") else None
        if comment:
            finding.details = {**(finding.details or {}), "resolution_comment": comment}
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.GOVERNANCE_FINDING_RESOLVED,
            organization_id=actor.organization_id, actor_id=actor.id, identity_id=finding.identity_id,
            meta={"finding_id": str(finding.id), "status": status},
        )
        return finding


# --------------------------------------------------------------------------- #
# Remediation (§14, §17)
# --------------------------------------------------------------------------- #
class RemediationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def get_or_404(self, actor: User, action_id: uuid.UUID) -> RemediationAction:
        action = self.db.get(RemediationAction, action_id)
        if action is None or action.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.REMEDIATION_ACTION_NOT_FOUND, "Remediation action not found.")
        return action

    def list(self, actor: User, *, status: str | None = None,
             finding_id: uuid.UUID | None = None) -> list[RemediationAction]:
        stmt = select(RemediationAction).where(RemediationAction.organization_id == actor.organization_id)
        if status:
            stmt = stmt.where(RemediationAction.status == status)
        if finding_id:
            stmt = stmt.where(RemediationAction.finding_id == finding_id)
        return list(self.db.execute(stmt.order_by(RemediationAction.created_at.desc())).scalars())

    def create(self, actor: User, payload: dict) -> RemediationAction:
        finding = self.db.get(GovernanceFinding, payload["finding_id"])
        if finding is None or finding.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.GOVERNANCE_FINDING_NOT_FOUND, "Finding not found.")
        action = RemediationAction(organization_id=actor.organization_id, created_by=actor.id, **payload)
        self.db.add(action)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.REMEDIATION_CREATED,
            organization_id=actor.organization_id, actor_id=actor.id, identity_id=finding.identity_id,
            meta={"action_id": str(action.id), "finding_id": str(finding.id),
                  "action_type": action.action_type},
        )
        if action.mode == "AUTOMATIC":
            self.execute(actor, action.id)
        return action

    def execute(self, actor: User, action_id: uuid.UUID) -> RemediationAction:
        action = self.get_or_404(actor, action_id)
        if action.status == "EXECUTED":
            raise IdentityError(ErrorCode.REMEDIATION_ALREADY_EXECUTED, "Already executed.")
        finding = self.db.get(GovernanceFinding, action.finding_id)
        try:
            self._dispatch(actor, action, finding)
            action.status = "EXECUTED"
        except IdentityError:
            action.status = "FAILED"
            raise
        finally:
            action.executed_by = actor.id
            action.executed_at = _now()
            self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.REMEDIATION_EXECUTED,
            organization_id=actor.organization_id, actor_id=actor.id,
            identity_id=finding.identity_id if finding else None,
            meta={"action_id": str(action.id), "action_type": action.action_type,
                  "status": action.status},
        )
        return action

    def _dispatch(self, actor: User, action: RemediationAction,
                  finding: GovernanceFinding | None) -> None:
        payload = action.payload or {}
        identity_id = finding.identity_id if finding else None

        if action.action_type == "REMOVE_ROLE":
            assignment_id = payload.get("assignment_id")
            if assignment_id:
                RoleAssignmentService(self.db).remove(
                    uuid.UUID(str(assignment_id)),
                    organization_id=actor.organization_id, actor_id=actor.id,
                )
        elif action.action_type == "DISABLE_ACCOUNT":
            user = self.db.get(User, identity_id) if identity_id else None
            if user is not None:
                user.is_active = False
                user.status = "DISABLED"
        elif action.action_type == "DISABLE_API_KEY":
            key_id = payload.get("api_key_id")
            if key_id:
                key = self.db.get(AgentApiKey, uuid.UUID(str(key_id)))
                if key is not None:
                    key.status = ApiKeyStatus.REVOKED
        elif action.action_type == "EXPIRE_DELEGATION":
            delegation_id = payload.get("delegation_id")
            if delegation_id:
                delegation = self.db.get(Delegation, uuid.UUID(str(delegation_id)))
                if delegation is not None:
                    delegation.revoked_at = _now()
        elif action.action_type in ("NOTIFY_MANAGER", "CREATE_APPROVAL_REQUEST",
                                    "REQUIRE_MFA", "CREATE_SECURITY_TICKET"):
            # No manager hierarchy / ticketing / per-user MFA-required flag exists
            # yet in this codebase (see docs/governance/remediation.md) — the
            # action is still tracked to EXECUTED via the audit trail so the
            # governance record stays authoritative.
            pass
        else:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown remediation action type.")


# --------------------------------------------------------------------------- #
# Governance risk scoring (§13)
# --------------------------------------------------------------------------- #
class GovernanceRiskScoringService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def compute_for_identity(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> GovernanceRiskScore | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None

        privileged_roles = int(self.db.execute(
            select(func.count()).select_from(UserRole).join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.name.in_(PRIVILEGED_ROLE_NAMES))
        ).scalar() or 0)
        toxic_findings = int(self.db.execute(
            select(func.count()).select_from(GovernanceFinding).where(
                GovernanceFinding.identity_id == user_id, GovernanceFinding.status == "OPEN",
                GovernanceFinding.finding_type.in_(("SOD_VIOLATION", "TOXIC_PERMISSION")))
        ).scalar() or 0)
        last_activity = self.db.execute(
            select(func.max(UserSession.last_activity_at)).where(UserSession.user_id == user_id)
        ).scalar()
        reference = last_activity or user.created_at
        inactive_days = max(0, (_now() - reference).days)
        failed_reviews = int(self.db.execute(
            select(func.count()).select_from(AccessReviewItem)
            .where(AccessReviewItem.subject_id == user_id, AccessReviewItem.decision == "REVOKED")
        ).scalar() or 0)
        outstanding_approvals = int(self.db.execute(
            select(func.count()).select_from(Approval)
            .where(Approval.assigned_to_user_id == user_id, Approval.decision == "PENDING")
        ).scalar() or 0)

        score = 0
        score += min(30, privileged_roles * 15)
        score += min(30, toxic_findings * 15)
        if inactive_days > INACTIVITY_THRESHOLD_DAYS:
            score += min(20, ((inactive_days - INACTIVITY_THRESHOLD_DAYS) // 30 + 1) * 5)
        score += min(10, failed_reviews * 5)
        score += min(10, outstanding_approvals * 2)
        score = min(100, score)
        band = _band_for(score)
        factors = {
            "privileged_roles": privileged_roles,
            "open_toxic_or_sod_findings": toxic_findings,
            "inactive_days": inactive_days,
            "failed_reviews": failed_reviews,
            "outstanding_approvals": outstanding_approvals,
        }

        existing = self.db.execute(
            select(GovernanceRiskScore).where(
                GovernanceRiskScore.organization_id == organization_id,
                GovernanceRiskScore.identity_id == user_id)
        ).scalar_one_or_none()
        if existing is None:
            existing = GovernanceRiskScore(organization_id=organization_id, identity_id=user_id)
            self.db.add(existing)
        existing.identity_label = user.email
        existing.score = score
        existing.band = band
        existing.factors = factors
        existing.computed_at = _now()
        self.db.flush()
        return existing

    def compute_all(self, actor: User) -> list[GovernanceRiskScore]:
        user_ids = list(self.db.execute(
            select(User.id).where(User.organization_id == actor.organization_id, User.is_active.is_(True))
        ).scalars())
        for user_id in user_ids:
            self.compute_for_identity(user_id, actor.organization_id)
        rows = self.list(actor)
        self.audit.record_change(
            AuthorizationAuditEvent.RISK_SCORE_COMPUTED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"identities": len(rows)},
        )
        return rows

    def list(self, actor: User, *, band: str | None = None) -> list[GovernanceRiskScore]:
        stmt = select(GovernanceRiskScore).where(GovernanceRiskScore.organization_id == actor.organization_id)
        if band:
            stmt = stmt.where(GovernanceRiskScore.band == band)
        return list(self.db.execute(stmt.order_by(GovernanceRiskScore.score.desc())).scalars())


# --------------------------------------------------------------------------- #
# Privileged access governance (§11)
# --------------------------------------------------------------------------- #
class PrivilegedAccessReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def list_accounts(self, actor: User) -> list[dict]:
        stmt = (
            select(UserRole, User, Role)
            .join(User, User.id == UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.organization_id == actor.organization_id, Role.name.in_(PRIVILEGED_ROLE_NAMES))
        )
        rows = self.db.execute(stmt).all()

        latest_review: dict[uuid.UUID, PrivilegedAccountReview] = {}
        for review in self.db.execute(
            select(PrivilegedAccountReview)
            .where(PrivilegedAccountReview.organization_id == actor.organization_id)
            .order_by(PrivilegedAccountReview.created_at.desc())
        ).scalars():
            latest_review.setdefault(review.identity_id, review)

        risk = GovernanceRiskScoringService(self.db)
        result: list[dict] = []
        for assignment, user, role in rows:
            score_row = self.db.execute(
                select(GovernanceRiskScore).where(
                    GovernanceRiskScore.organization_id == actor.organization_id,
                    GovernanceRiskScore.identity_id == user.id)
            ).scalar_one_or_none() or risk.compute_for_identity(user.id, actor.organization_id)
            last_activity = self.db.execute(
                select(func.max(UserSession.last_activity_at)).where(UserSession.user_id == user.id)
            ).scalar()
            review = latest_review.get(user.id)
            result.append({
                "identity_id": user.id, "identity_label": user.email, "role_name": role.name,
                "assignment_id": assignment.id,
                "risk_score": score_row.score if score_row else 0,
                "risk_band": score_row.band if score_row else "LOW",
                "last_activity_at": last_activity,
                "review_status": review.status if review else None,
                "review_due_at": review.due_at if review else None,
            })
        return result

    def request_review(self, actor: User, *, identity_id: uuid.UUID,
                       role_name: str) -> PrivilegedAccountReview:
        user = self.db.get(User, identity_id)
        if user is None or user.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "User not found.")
        score = GovernanceRiskScoringService(self.db).compute_for_identity(identity_id, actor.organization_id)
        review = PrivilegedAccountReview(
            organization_id=actor.organization_id, identity_id=identity_id, identity_label=user.email,
            role_name=role_name, risk_score=score.score if score else None,
            due_at=_now() + timedelta(days=30),
        )
        self.db.add(review)
        self.db.flush()
        return review

    def list_reviews(self, actor: User, *, status: str | None = None) -> list[PrivilegedAccountReview]:
        stmt = select(PrivilegedAccountReview).where(
            PrivilegedAccountReview.organization_id == actor.organization_id)
        if status:
            stmt = stmt.where(PrivilegedAccountReview.status == status)
        return list(self.db.execute(stmt.order_by(PrivilegedAccountReview.created_at.desc())).scalars())

    def decide(self, actor: User, review_id: uuid.UUID, *, decision: str,
              comment: str | None, assignment_id: uuid.UUID | None) -> PrivilegedAccountReview:
        review = self.db.get(PrivilegedAccountReview, review_id)
        if review is None or review.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.PRIVILEGED_REVIEW_NOT_FOUND, "Privileged review not found.")
        review.status = decision
        review.reviewed_by = actor.id
        review.reviewed_at = _now()
        if decision == "REVOKED" and assignment_id is not None:
            try:
                RoleAssignmentService(self.db).remove(
                    assignment_id, organization_id=actor.organization_id, actor_id=actor.id)
            except IdentityError:
                pass  # already removed elsewhere — the review decision stands
        self.db.flush()
        # PrivilegedAccountReview has no comment column — carry it in the audit
        # trail rather than silently discarding a reviewer's justification.
        meta = {"review_id": str(review.id), "decision": decision, "role": review.role_name}
        if comment:
            meta["comment"] = comment
        self.audit.record_change(
            AuthorizationAuditEvent.PRIVILEGED_REVIEW_COMPLETED,
            organization_id=actor.organization_id, actor_id=actor.id, identity_id=review.identity_id,
            meta=meta,
        )
        return review


# --------------------------------------------------------------------------- #
# Orphaned identity detection (§12)
# --------------------------------------------------------------------------- #
class OrphanedIdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def _existing(self, organization_id: uuid.UUID) -> set[tuple]:
        rows = self.db.execute(
            select(GovernanceFinding.identity_id, GovernanceFinding.resource_id).where(
                GovernanceFinding.organization_id == organization_id,
                GovernanceFinding.finding_type == "ORPHANED_ACCOUNT",
                GovernanceFinding.status == "OPEN",
            )
        ).all()
        return {(identity_id, resource_id) for identity_id, resource_id in rows}

    def _raise(self, actor: User, seen: set[tuple], *, identity_id: uuid.UUID | None,
              identity_label: str, resource_id: uuid.UUID | None, reason: str, detail: dict) -> int:
        key = (identity_id, resource_id)
        if key in seen:
            return 0
        seen.add(key)
        finding = GovernanceFinding(
            organization_id=actor.organization_id, finding_type="ORPHANED_ACCOUNT",
            severity="MEDIUM", identity_id=identity_id, identity_label=identity_label,
            resource_id=resource_id, details={"reason": reason, **detail},
        )
        self.db.add(finding)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ORPHANED_ACCOUNT_DETECTED,
            organization_id=actor.organization_id, actor_id=actor.id, identity_id=identity_id,
            meta={"finding_id": str(finding.id), "reason": reason},
        )
        return 1

    def scan(self, actor: User) -> dict:
        org = actor.organization_id
        seen = self._existing(org)
        created = 0

        # 1. Disabled users who still hold active role assignments.
        disabled_with_roles = self.db.execute(
            select(User, UserRole).join(UserRole, UserRole.user_id == User.id)
            .where(User.organization_id == org, User.is_active.is_(False))
        ).all()
        disabled_seen: set[uuid.UUID] = set()
        for user, _assignment in disabled_with_roles:
            if user.id in disabled_seen:
                continue
            disabled_seen.add(user.id)
            created += self._raise(actor, seen, identity_id=user.id, identity_label=user.email,
                                   resource_id=None, reason="DISABLED_WITH_ACTIVE_ACCESS",
                                   detail={})

        # 2. No activity for > 90 days while still holding role assignments.
        # Batched: one grouped query for last-activity and one for "has any role"
        # across every active user, instead of two round-trips per user.
        cutoff = _now() - timedelta(days=INACTIVITY_THRESHOLD_DAYS)
        active_users = list(self.db.execute(
            select(User).where(User.organization_id == org, User.is_active.is_(True))
        ).scalars())
        active_user_ids = [u.id for u in active_users]
        last_activity_by_user = dict(self.db.execute(
            select(UserSession.user_id, func.max(UserSession.last_activity_at))
            .where(UserSession.user_id.in_(active_user_ids))
            .group_by(UserSession.user_id)
        ).all()) if active_user_ids else {}
        users_with_roles = set(self.db.execute(
            select(UserRole.user_id.distinct()).where(UserRole.user_id.in_(active_user_ids))
        ).scalars()) if active_user_ids else set()
        for user in active_users:
            reference = last_activity_by_user.get(user.id) or user.created_at
            if reference >= cutoff:
                continue
            if user.id not in users_with_roles:
                continue
            created += self._raise(actor, seen, identity_id=user.id, identity_label=user.email,
                                   resource_id=None, reason="INACTIVE_OVER_90_DAYS",
                                   detail={"last_activity": reference.isoformat()})

        # 3. Stale API keys — active, unused for > 90 days.
        stale_keys = self.db.execute(
            select(AgentApiKey, Agent).join(Agent, Agent.id == AgentApiKey.agent_id)
            .where(Agent.organization_id == org, AgentApiKey.status == ApiKeyStatus.ACTIVE,
                   (AgentApiKey.last_used_at.is_(None)) | (AgentApiKey.last_used_at < cutoff))
        ).all()
        for key, agent in stale_keys:
            created += self._raise(actor, seen, identity_id=None, identity_label=agent.name,
                                   resource_id=key.id, reason="STALE_API_KEY",
                                   detail={"agent_id": str(agent.id), "key_prefix": key.key_prefix})

        # 4. Roles with zero assignments.
        unused_roles = self.db.execute(
            select(Role).outerjoin(UserRole, UserRole.role_id == Role.id)
            .where(Role.organization_id == org, Role.status == "ACTIVE")
            .group_by(Role.id).having(func.count(UserRole.id) == 0)
        ).scalars().all()
        for role in unused_roles:
            created += self._raise(actor, seen, identity_id=None, identity_label=role.name,
                                   resource_id=role.id, reason="UNUSED_ROLE", detail={})

        return {
            "scanned_users": len(active_users) + len(disabled_seen),
            "scanned_api_keys": len(stale_keys),
            "scanned_roles": len(unused_roles),
            "findings_created": created,
        }


# --------------------------------------------------------------------------- #
# Compliance reporting (§15, §16)
# --------------------------------------------------------------------------- #
FRAMEWORK_CONTROLS: dict[str, list[dict]] = {
    "SOC2": [{"control": "Logical Access", "platform_evidence": "Certification campaigns"}],
    "ISO27001": [{"control": "Access Control", "platform_evidence": "RBAC + access reviews"}],
    "HIPAA": [{"control": "Workforce Access", "platform_evidence": "Role assignments + audit trail"}],
    "GDPR": [{"control": "Least Privilege", "platform_evidence": "Access reviews + SoD findings"}],
    "NIST": [{"control": "Account Management (AC-2)", "platform_evidence": "Identity lifecycle + orphaned-account detection"}],
    "CIS": [{"control": "Access Control Management", "platform_evidence": "SoD/toxic-permission rules + findings"}],
    "INTERNAL": [{"control": "Organizational Policy", "platform_evidence": "Governance findings + remediation log"}],
}
FRAMEWORK_DISPLAY_NAMES: dict[str, str] = {
    "SOC2": "SOC 2", "ISO27001": "ISO/IEC 27001", "HIPAA": "HIPAA", "GDPR": "GDPR",
    "NIST": "NIST SP 800-53", "CIS": "CIS Controls", "INTERNAL": "Internal Organizational Policy",
}


class ComplianceReportingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def frameworks(self) -> list[dict]:
        return [{"framework": k, "display_name": FRAMEWORK_DISPLAY_NAMES[k], "controls": v}
                for k, v in FRAMEWORK_CONTROLS.items()]

    def get_or_404(self, actor: User, report_id: uuid.UUID) -> ComplianceReport:
        report = self.db.get(ComplianceReport, report_id)
        if report is None or report.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.COMPLIANCE_REPORT_NOT_FOUND, "Compliance report not found.")
        return report

    def list(self, actor: User, *, framework: str | None = None) -> list[ComplianceReport]:
        stmt = select(ComplianceReport).where(ComplianceReport.organization_id == actor.organization_id)
        if framework:
            stmt = stmt.where(ComplianceReport.framework == framework)
        return list(self.db.execute(stmt.order_by(ComplianceReport.generated_at.desc())).scalars())

    def generate(self, actor: User, *, framework: str, report_type: str,
                scope: dict | None) -> ComplianceReport:
        org = actor.organization_id

        def count(stmt) -> int:
            return int(self.db.execute(stmt).scalar() or 0)

        evidence = {
            "generated_at": _now().isoformat(),
            "scope": scope or {"organization_id": str(org)},
            "certification_campaigns": {
                "completed": count(select(func.count()).select_from(AccessReviewCampaign).where(
                    AccessReviewCampaign.organization_id == org, AccessReviewCampaign.status == "COMPLETED")),
                "active": count(select(func.count()).select_from(AccessReviewCampaign).where(
                    AccessReviewCampaign.organization_id == org, AccessReviewCampaign.status == "ACTIVE")),
            },
            "sod_findings_open": count(select(func.count()).select_from(GovernanceFinding).where(
                GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "SOD_VIOLATION",
                GovernanceFinding.status == "OPEN")),
            "toxic_permission_findings_open": count(select(func.count()).select_from(GovernanceFinding).where(
                GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "TOXIC_PERMISSION",
                GovernanceFinding.status == "OPEN")),
            "orphaned_account_findings_open": count(select(func.count()).select_from(GovernanceFinding).where(
                GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "ORPHANED_ACCOUNT",
                GovernanceFinding.status == "OPEN")),
            "findings_remediated": count(select(func.count()).select_from(GovernanceFinding).where(
                GovernanceFinding.organization_id == org, GovernanceFinding.status == "REMEDIATED")),
            "privileged_reviews_completed": count(select(func.count()).select_from(PrivilegedAccountReview).where(
                PrivilegedAccountReview.organization_id == org, PrivilegedAccountReview.status != "PENDING")),
            "risk_distribution": dict(self.db.execute(
                select(GovernanceRiskScore.band, func.count()).where(
                    GovernanceRiskScore.organization_id == org).group_by(GovernanceRiskScore.band)).all()),
            "controls": FRAMEWORK_CONTROLS.get(framework, []),
        }
        report = ComplianceReport(
            organization_id=org, framework=framework, report_type=report_type,
            scope=scope, payload=evidence, generated_by=actor.id,
        )
        self.db.add(report)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.COMPLIANCE_REPORT_GENERATED,
            organization_id=org, actor_id=actor.id,
            meta={"report_id": str(report.id), "framework": framework},
        )
        return report

    @staticmethod
    def to_csv(report: ComplianceReport) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["metric", "value"])

        def flatten(prefix: str, obj) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    flatten(f"{prefix}.{k}" if prefix else k, v)
            elif isinstance(obj, list):
                writer.writerow([prefix, "; ".join(str(x) for x in obj)])
            else:
                writer.writerow([prefix, obj])

        flatten("", report.payload)
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# Governance dashboard + analytics (§21, §26)
# --------------------------------------------------------------------------- #
class GovernanceDashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshot(self, actor: User) -> dict:
        org = actor.organization_id

        def count(stmt) -> int:
            return int(self.db.execute(stmt).scalar() or 0)

        active_campaigns = count(select(func.count()).select_from(AccessReviewCampaign).where(
            AccessReviewCampaign.organization_id == org, AccessReviewCampaign.status == "ACTIVE"))
        pending_reviews = count(
            select(func.count()).select_from(AccessReviewItem)
            .join(AccessReviewCampaign, AccessReviewCampaign.id == AccessReviewItem.campaign_id)
            .where(AccessReviewCampaign.organization_id == org, AccessReviewItem.decision == "PENDING",
                   AccessReviewCampaign.status == "ACTIVE"))
        overdue_reviews = count(select(func.count()).select_from(AccessReviewCampaign).where(
            AccessReviewCampaign.organization_id == org, AccessReviewCampaign.status == "ACTIVE",
            AccessReviewCampaign.due_at.is_not(None), AccessReviewCampaign.due_at < _now()))
        privileged_accounts = count(
            select(func.count(func.distinct(UserRole.user_id))).select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id).join(User, User.id == UserRole.user_id)
            .where(User.organization_id == org, Role.name.in_(PRIVILEGED_ROLE_NAMES)))
        toxic_findings = count(select(func.count()).select_from(GovernanceFinding).where(
            GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "TOXIC_PERMISSION",
            GovernanceFinding.status == "OPEN"))
        sod_findings = count(select(func.count()).select_from(GovernanceFinding).where(
            GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "SOD_VIOLATION",
            GovernanceFinding.status == "OPEN"))
        orphaned = count(select(func.count()).select_from(GovernanceFinding).where(
            GovernanceFinding.organization_id == org, GovernanceFinding.finding_type == "ORPHANED_ACCOUNT",
            GovernanceFinding.status == "OPEN"))
        remediation_queue = count(select(func.count()).select_from(RemediationAction).where(
            RemediationAction.organization_id == org, RemediationAction.status == "PENDING"))
        compliance_reports_total = count(select(func.count()).select_from(ComplianceReport).where(
            ComplianceReport.organization_id == org))
        risk_dist = dict(self.db.execute(
            select(GovernanceRiskScore.band, func.count()).where(
                GovernanceRiskScore.organization_id == org).group_by(GovernanceRiskScore.band)).all())

        widgets = {
            "active_campaigns": active_campaigns,
            "pending_reviews": pending_reviews,
            "overdue_reviews": overdue_reviews,
            "privileged_accounts": privileged_accounts,
            "toxic_permission_findings": toxic_findings,
            "sod_findings": sod_findings,
            "orphaned_accounts": orphaned,
            "compliance_status": "ready" if compliance_reports_total else "no_reports_yet",
            "remediation_queue": remediation_queue,
            "governance_risk_distribution": risk_dist,
        }
        return {"widgets": widgets, "charts": self.analytics(actor)}

    def analytics(self, actor: User) -> dict:
        org = actor.organization_id
        month_ago = _now() - timedelta(days=30)

        completion_rows = self.db.execute(
            select(AccessReviewCampaign.completed_at).where(
                AccessReviewCampaign.organization_id == org, AccessReviewCampaign.status == "COMPLETED",
                AccessReviewCampaign.completed_at >= month_ago)
        ).all()
        completion_by_day: Counter[str] = Counter(r[0].date().isoformat() for r in completion_rows if r[0])

        severity_rows = self.db.execute(
            select(GovernanceFinding.severity, func.count()).where(
                GovernanceFinding.organization_id == org, GovernanceFinding.status == "OPEN")
            .group_by(GovernanceFinding.severity)
        ).all()
        type_rows = self.db.execute(
            select(GovernanceFinding.finding_type, func.count()).where(
                GovernanceFinding.organization_id == org).group_by(GovernanceFinding.finding_type)
        ).all()
        priv_rows = self.db.execute(
            select(UserRole.created_at).join(Role, Role.id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(User.organization_id == org, Role.name.in_(PRIVILEGED_ROLE_NAMES))
        ).all()
        priv_by_month: Counter[str] = Counter(r[0].strftime("%Y-%m") for r in priv_rows if r[0])
        risk_rows = self.db.execute(
            select(GovernanceRiskScore.band, func.count()).where(
                GovernanceRiskScore.organization_id == org).group_by(GovernanceRiskScore.band)
        ).all()

        return {
            "review_completion_trend": [{"date": d, "completed": n}
                                        for d, n in sorted(completion_by_day.items())],
            "findings_by_severity": [{"severity": s, "total": n} for s, n in severity_rows],
            "findings_by_type": [{"finding_type": t, "total": n} for t, n in type_rows],
            "privileged_access_growth": [{"month": m, "total": n} for m, n in sorted(priv_by_month.items())],
            "risk_score_distribution": [{"band": b, "total": n} for b, n in risk_rows],
        }
