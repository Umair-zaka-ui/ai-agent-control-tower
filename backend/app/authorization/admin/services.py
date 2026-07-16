"""Administration portal services (Phase 4.3.7).

DashboardService (§6), DecisionExplorerService (§13), AccessReviewService
(§14) and SecurityAnalyticsService (§17). Everything is tenant-scoped to the
acting administrator's organization; mutations go through the existing phase
services (RBAC assignment removal on revoke) — never raw SQL.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService, RoleAssignmentService
from app.core.enums import ApprovalDecision
from app.identity.errors import ErrorCode, IdentityError
from app.models.abac import ABACEvaluation, ABACPolicy
from app.models.access_review import AccessReviewCampaign, AccessReviewItem
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.models.rbac import AuthorizationDecision, RbacPermission, Role, UserRole
from app.models.user import User

HIGH_RISK_THRESHOLD = 70


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Dashboard (§6)
# --------------------------------------------------------------------------- #
class DashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshot(self, actor: User) -> dict:
        from app.authorization.middleware.metrics import PipelineMetricsService
        from app.identity.models.session import UserSession

        org = actor.organization_id
        day_ago = _now() - timedelta(hours=24)

        def count(stmt) -> int:
            return int(self.db.execute(stmt).scalar() or 0)

        users = count(select(func.count()).select_from(User).where(User.organization_id == org))
        roles = count(select(func.count()).select_from(Role).where(
            Role.status == "ACTIVE",
            (Role.organization_id == org) | (Role.organization_id.is_(None))))
        permissions = count(select(func.count()).select_from(RbacPermission))
        policies = count(select(func.count()).select_from(ABACPolicy).where(
            ABACPolicy.status == "ACTIVE",
            (ABACPolicy.organization_id == org) | (ABACPolicy.organization_id.is_(None))))
        sessions = count(
            select(func.count()).select_from(UserSession)
            .join(User, User.id == UserSession.user_id)
            .where(User.organization_id == org, UserSession.status == "ACTIVE"))
        requests_24h = count(select(func.count()).select_from(AuthorizationDecision).where(
            AuthorizationDecision.organization_id == org,
            AuthorizationDecision.created_at >= day_ago))
        denied_24h = count(select(func.count()).select_from(AuthorizationDecision).where(
            AuthorizationDecision.organization_id == org,
            AuthorizationDecision.allowed.is_(False),
            AuthorizationDecision.created_at >= day_ago))
        approvals_pending = count(select(func.count()).select_from(Approval).where(
            Approval.organization_id == org,
            Approval.decision == ApprovalDecision.PENDING))
        high_risk_24h = count(select(func.count()).select_from(AgentAction).where(
            AgentAction.organization_id == org,
            AgentAction.risk_score >= HIGH_RISK_THRESHOLD,
            AgentAction.created_at >= day_ago))

        metrics = PipelineMetricsService.snapshot()
        widgets = {
            "total_users": users,
            "active_roles": roles,
            "active_permissions": permissions,
            "active_policies": policies,
            "active_sessions": sessions,
            "authorization_requests_24h": requests_24h,
            "denied_requests_24h": denied_24h,
            "approval_requests_pending": approvals_pending,
            "mfa_challenges_total": metrics["authorization_mfa_required_total"],
            "high_risk_decisions_24h": high_risk_24h,
            "cache_hit_ratio": metrics["decision_cache_hit_ratio"],
            "policy_evaluation_latency_ms": metrics["authorization_latency_ms_avg"],
        }
        return {"widgets": widgets, "charts": self._charts(org)}

    def _charts(self, org: uuid.UUID | None) -> dict:
        week_ago = _now() - timedelta(days=7)
        rows = self.db.execute(
            select(AuthorizationDecision.created_at, AuthorizationDecision.allowed,
                   AuthorizationDecision.permission)
            .where(AuthorizationDecision.organization_id == org,
                   AuthorizationDecision.created_at >= week_ago)
            .order_by(AuthorizationDecision.created_at.desc()).limit(2000)
        ).all()

        by_day: dict[str, dict] = {}
        by_permission: dict[str, dict] = {}
        for created_at, allowed, permission in rows:
            day = created_at.date().isoformat()
            d = by_day.setdefault(day, {"date": day, "total": 0, "denied": 0})
            d["total"] += 1
            p = by_permission.setdefault(permission, {"permission": permission,
                                                      "total": 0, "denied": 0})
            p["total"] += 1
            if not allowed:
                d["denied"] += 1
                p["denied"] += 1

        evaluations = self.db.execute(
            select(ABACEvaluation.decision, ABACEvaluation.matched_policy_ids,
                   ABACEvaluation.explanation)
            .where(ABACEvaluation.organization_id == org)
            .order_by(ABACEvaluation.created_at.desc()).limit(500)
        ).all()
        decision_counts: Counter[str] = Counter()
        policy_counts: Counter[str] = Counter()
        for decision, matched_ids, explanation in evaluations:
            decision_counts[decision] += 1
            names = {m.get("policy_id"): m.get("name") for m in
                     (explanation or {}).get("matched_policies", [])}
            for pid in matched_ids or []:
                policy_counts[names.get(pid) or str(pid)] += 1

        approvals = self.db.execute(
            select(Approval.decision, func.count()).where(Approval.organization_id == org)
            .group_by(Approval.decision)
        ).all()

        return {
            "authorization_trend": sorted(by_day.values(), key=lambda d: d["date"]),
            "top_permissions": sorted(by_permission.values(),
                                      key=lambda p: -p["total"])[:8],
            "policy_matches": [{"policy": name, "matches": n}
                               for name, n in policy_counts.most_common(8)],
            "decision_breakdown": [{"decision": d, "total": n}
                                   for d, n in decision_counts.most_common()],
            "approval_queue": [{"status": getattr(s, "value", s), "total": n}
                               for s, n in approvals],
        }


# --------------------------------------------------------------------------- #
# Decision explorer (§13)
# --------------------------------------------------------------------------- #
class DecisionExplorerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, actor: User, *, identity_id: uuid.UUID | None = None,
               permission: str | None = None, resource_type: str | None = None,
               allowed: bool | None = None, since: datetime | None = None,
               until: datetime | None = None, limit: int = 100) -> list[AuthorizationDecision]:
        stmt = select(AuthorizationDecision).where(
            AuthorizationDecision.organization_id == actor.organization_id)
        if identity_id is not None:
            stmt = stmt.where(AuthorizationDecision.identity_id == identity_id)
        if permission:
            stmt = stmt.where(AuthorizationDecision.permission.ilike(f"%{permission}%"))
        if resource_type:
            stmt = stmt.where(AuthorizationDecision.resource_type == resource_type)
        if allowed is not None:
            stmt = stmt.where(AuthorizationDecision.allowed.is_(allowed))
        if since is not None:
            stmt = stmt.where(AuthorizationDecision.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuthorizationDecision.created_at <= until)
        stmt = stmt.order_by(AuthorizationDecision.created_at.desc()).limit(min(limit, 500))
        rows = list(self.db.execute(stmt).scalars())
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.DECISION_VIEWED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"filters": {"identity_id": str(identity_id) if identity_id else None,
                              "permission": permission, "allowed": allowed},
                  "results": len(rows)},
        )
        return rows


# --------------------------------------------------------------------------- #
# Access reviews (§14)
# --------------------------------------------------------------------------- #
_CAMPAIGN_TRANSITIONS = {
    "DRAFT": {"SCHEDULED", "ACTIVE"},
    "SCHEDULED": {"ACTIVE"},
    "ACTIVE": {"COMPLETED"},
    "COMPLETED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


class AccessReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    # -- lookup ---------------------------------------------------------- #
    def get_or_404(self, actor: User, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        campaign = self.db.get(AccessReviewCampaign, campaign_id)
        if campaign is None or campaign.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Access review campaign not found.")
        return campaign

    def list(self, actor: User, *, status: str | None = None) -> list[AccessReviewCampaign]:
        stmt = select(AccessReviewCampaign).where(
            AccessReviewCampaign.organization_id == actor.organization_id)
        if status:
            stmt = stmt.where(AccessReviewCampaign.status == status)
        return list(self.db.execute(
            stmt.order_by(AccessReviewCampaign.created_at.desc())).scalars())

    def items(self, actor: User, campaign_id: uuid.UUID) -> list[AccessReviewItem]:
        self.get_or_404(actor, campaign_id)
        return list(self.db.execute(
            select(AccessReviewItem).where(AccessReviewItem.campaign_id == campaign_id)
            .order_by(AccessReviewItem.subject_label, AccessReviewItem.role_name)
        ).scalars())

    def counts(self, campaign_id: uuid.UUID) -> tuple[int, int, int]:
        rows = self.db.execute(
            select(AccessReviewItem.decision, func.count())
            .where(AccessReviewItem.campaign_id == campaign_id)
            .group_by(AccessReviewItem.decision)
        ).all()
        by = {d: n for d, n in rows}
        total = sum(by.values())
        return total, total - by.get("PENDING", 0), by.get("REVOKED", 0)

    # -- lifecycle -------------------------------------------------------- #
    def create(self, actor: User, payload: dict) -> AccessReviewCampaign:
        campaign = AccessReviewCampaign(
            organization_id=actor.organization_id, created_by=actor.id, **payload)
        self.db.add(campaign)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ACCESS_REVIEW_CREATED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"campaign_id": str(campaign.id), "name": campaign.name},
        )
        return campaign

    def update(self, actor: User, campaign_id: uuid.UUID, payload: dict) -> AccessReviewCampaign:
        campaign = self.get_or_404(actor, campaign_id)
        if campaign.status not in ("DRAFT", "SCHEDULED"):
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                                "Only draft or scheduled campaigns can be edited.")
        for key, value in payload.items():
            if value is not None:
                setattr(campaign, key, value)
        self.db.flush()
        return campaign

    def _transition(self, campaign: AccessReviewCampaign, to: str) -> None:
        if to not in _CAMPAIGN_TRANSITIONS[campaign.status]:
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                f"Cannot move a {campaign.status} campaign to {to}.",
            )
        campaign.status = to

    def schedule(self, actor: User, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        campaign = self.get_or_404(actor, campaign_id)
        self._transition(campaign, "SCHEDULED")
        self.db.flush()
        return campaign

    def activate(self, actor: User, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        """Snapshot every in-scope role assignment as a review item (§14)."""
        campaign = self.get_or_404(actor, campaign_id)
        self._transition(campaign, "ACTIVE")
        campaign.activated_at = _now()

        scope = campaign.scope or {}
        role_ids = {uuid.UUID(r) for r in scope.get("role_ids", [])} or None
        stmt = (
            select(UserRole, User, Role)
            .join(User, User.id == UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.organization_id == campaign.organization_id)
        )
        if not scope.get("include_system_roles", True):
            stmt = stmt.where(Role.is_system.is_(False))
        count = 0
        for assignment, user, role in self.db.execute(stmt).all():
            if role_ids is not None and assignment.role_id not in role_ids:
                continue
            self.db.add(AccessReviewItem(
                campaign_id=campaign.id, subject_id=user.id,
                subject_label=user.email, assignment_id=assignment.id,
                role_id=role.id, role_name=role.name,
                scope_label=assignment.scope,
            ))
            count += 1
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ACCESS_REVIEW_ACTIVATED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"campaign_id": str(campaign.id), "items": count},
        )
        return campaign

    def decide_item(self, actor: User, campaign_id: uuid.UUID, item_id: uuid.UUID,
                    *, decision: str, comment: str | None) -> AccessReviewItem:
        campaign = self.get_or_404(actor, campaign_id)
        if campaign.status != "ACTIVE":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                                "Decisions are only recorded on active campaigns.")
        item = self.db.get(AccessReviewItem, item_id)
        if item is None or item.campaign_id != campaign.id:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Review item not found.")

        item.decision = decision
        item.decided_by = actor.id
        item.decided_at = _now()
        item.comment = comment

        # A revoke is real enforcement: the underlying assignment is removed
        # through the RBAC service so caches invalidate and audit fires (§14).
        if decision == "REVOKED" and item.assignment_id is not None:
            try:
                RoleAssignmentService(self.db).remove(
                    item.assignment_id,
                    organization_id=actor.organization_id, actor_id=actor.id,
                )
                from app.authorization.cache import PermissionCacheService

                PermissionCacheService(self.db).invalidate_org(actor.organization_id)
            except IdentityError:
                pass  # already removed elsewhere — the certification stands

        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ACCESS_REVIEW_ITEM_DECIDED,
            organization_id=actor.organization_id, actor_id=actor.id,
            identity_id=item.subject_id,
            meta={"campaign_id": str(campaign.id), "item_id": str(item.id),
                  "decision": decision, "role": item.role_name},
        )
        return item

    def complete(self, actor: User, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        campaign = self.get_or_404(actor, campaign_id)
        total, decided, _ = self.counts(campaign_id)
        if decided < total:
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                f"{total - decided} review item(s) are still pending.",
            )
        self._transition(campaign, "COMPLETED")
        campaign.completed_at = _now()
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ACCESS_REVIEW_COMPLETED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"campaign_id": str(campaign.id), "items": total},
        )
        return campaign

    def archive(self, actor: User, campaign_id: uuid.UUID) -> AccessReviewCampaign:
        campaign = self.get_or_404(actor, campaign_id)
        self._transition(campaign, "ARCHIVED")
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ACCESS_REVIEW_ARCHIVED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"campaign_id": str(campaign.id)},
        )
        return campaign

    def export(self, actor: User, campaign_id: uuid.UUID) -> dict:
        campaign = self.get_or_404(actor, campaign_id)
        items = self.items(actor, campaign_id)
        self.audit.record_change(
            AuthorizationAuditEvent.AUDIT_EXPORTED,
            organization_id=actor.organization_id, actor_id=actor.id,
            meta={"campaign_id": str(campaign.id), "items": len(items),
                  "export": "access_review"},
        )
        return {
            "campaign": {
                "id": str(campaign.id), "name": campaign.name,
                "status": campaign.status,
                "activated_at": campaign.activated_at.isoformat() if campaign.activated_at else None,
                "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
            },
            "items": [{
                "subject": i.subject_label, "role": i.role_name,
                "scope": i.scope_label, "decision": i.decision,
                "comment": i.comment,
                "decided_at": i.decided_at.isoformat() if i.decided_at else None,
            } for i in items],
        }


# --------------------------------------------------------------------------- #
# Security analytics (§17)
# --------------------------------------------------------------------------- #
class SecurityAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshot(self, actor: User) -> dict:
        from app.authorization.abac.engine import ABACMetrics
        from app.authorization.middleware.metrics import PipelineMetricsService

        org = actor.organization_id
        now = _now()
        day_ago, week_ago = now - timedelta(hours=24), now - timedelta(days=7)

        def count(stmt) -> int:
            return int(self.db.execute(stmt).scalar() or 0)

        denied_24h = count(select(func.count()).select_from(AuthorizationDecision).where(
            AuthorizationDecision.organization_id == org,
            AuthorizationDecision.allowed.is_(False),
            AuthorizationDecision.created_at >= day_ago))
        denied_7d = count(select(func.count()).select_from(AuthorizationDecision).where(
            AuthorizationDecision.organization_id == org,
            AuthorizationDecision.allowed.is_(False),
            AuthorizationDecision.created_at >= week_ago))
        high_risk_24h = count(select(func.count()).select_from(AgentAction).where(
            AgentAction.organization_id == org,
            AgentAction.risk_score >= HIGH_RISK_THRESHOLD,
            AgentAction.created_at >= day_ago))

        approvals = self.db.execute(
            select(Approval.decision, func.count()).where(Approval.organization_id == org)
            .group_by(Approval.decision)).all()
        by_status = {getattr(s, "value", s): n for s, n in approvals}
        total_approvals = sum(by_status.values())
        approved = by_status.get("APPROVED", 0)

        top_denied = self.db.execute(
            select(AuthorizationDecision.permission, func.count())
            .where(AuthorizationDecision.organization_id == org,
                   AuthorizationDecision.allowed.is_(False))
            .group_by(AuthorizationDecision.permission)
            .order_by(func.count().desc()).limit(8)).all()

        denied_rows = self.db.execute(
            select(AuthorizationDecision.created_at)
            .where(AuthorizationDecision.organization_id == org,
                   AuthorizationDecision.allowed.is_(False),
                   AuthorizationDecision.created_at >= week_ago)).all()
        denied_by_day: Counter[str] = Counter(
            r[0].date().isoformat() for r in denied_rows)

        from app.models.resource_authorization import ResourceShare

        share_rows = self.db.execute(
            select(ResourceShare.created_at).where(ResourceShare.created_at >= week_ago)
        ).all()
        shares_by_day: Counter[str] = Counter(r[0].date().isoformat() for r in share_rows)

        pipeline = PipelineMetricsService.snapshot()
        abac = ABACMetrics.snapshot()
        return {
            "denied_requests_24h": denied_24h,
            "denied_requests_7d": denied_7d,
            "high_risk_decisions_24h": high_risk_24h,
            "mfa_challenges_total": pipeline["authorization_mfa_required_total"],
            "approval_requests_total": total_approvals,
            "approval_approval_rate": round(approved / total_approvals, 3) if total_approvals else 0.0,
            "authorization_latency_ms_avg": pipeline["authorization_latency_ms_avg"],
            "authorization_latency_ms_p95": pipeline["authorization_latency_ms_p95"],
            "cache_hit_ratio": pipeline["decision_cache_hit_ratio"],
            "abac_denies_total": abac["abac_denies_total"],
            "abac_challenges_total": abac["abac_challenges_total"],
            "policy_errors_total": pipeline["authorization_policy_errors_total"],
            "top_denied_permissions": [{"permission": p, "denied": n} for p, n in top_denied],
            "denied_trend": [{"date": d, "denied": n} for d, n in sorted(denied_by_day.items())],
            "sharing_trend": [{"date": d, "shares": n} for d, n in sorted(shares_by_day.items())],
        }
