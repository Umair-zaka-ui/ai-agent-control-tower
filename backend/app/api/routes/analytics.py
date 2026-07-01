"""Analytics & AI Operations Center routes (Phase 3 Part 3.6).

Read-only, RBAC-gated executive/operations analytics derived from the existing
operational tables. ``analytics.view`` gates the analytics surfaces;
``analytics.executive`` and ``analytics.operations`` gate the executive and
operations dashboards respectively (enforced primarily in the UI, with the data
endpoints behind ``analytics.view``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.user import User
from app.schemas.analytics import (
    ActivityPoint,
    AnalyticsOverview,
    AnalyticsReport,
    CostAnalytics,
    FleetHealth,
    HumanReviewAnalytics,
    Insight,
    KpiMetric,
    PerformanceAnalytics,
    PolicyAnalytics,
    RiskAnalytics,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> AnalyticsOverview:
    """Composite landing payload: KPIs, fleet health, risk, activity, insights."""
    return analytics_service.overview(db, current_user.organization_id)


@router.get("/kpis", response_model=list[KpiMetric])
def analytics_kpis(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> list[KpiMetric]:
    return analytics_service.kpis(db, current_user.organization_id)


@router.get("/activity", response_model=list[ActivityPoint])
def analytics_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
    range: str = Query(default="daily", pattern="^(daily|weekly|monthly|yearly)$"),
) -> list[ActivityPoint]:
    return analytics_service.activity(db, current_user.organization_id, range)


@router.get("/fleet-health", response_model=FleetHealth)
def analytics_fleet_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> FleetHealth:
    return analytics_service.fleet_health(db, current_user.organization_id)


@router.get("/risk", response_model=RiskAnalytics)
def analytics_risk(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> RiskAnalytics:
    return analytics_service.risk_analytics(db, current_user.organization_id)


@router.get("/performance", response_model=PerformanceAnalytics)
def analytics_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> PerformanceAnalytics:
    return analytics_service.performance_analytics(db, current_user.organization_id)


@router.get("/policies", response_model=PolicyAnalytics)
def analytics_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> PolicyAnalytics:
    return analytics_service.policy_analytics(db, current_user.organization_id)


@router.get("/review", response_model=HumanReviewAnalytics)
def analytics_review(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> HumanReviewAnalytics:
    return analytics_service.human_review_analytics(db, current_user.organization_id)


@router.get("/cost", response_model=CostAnalytics)
def analytics_cost(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> CostAnalytics:
    return analytics_service.cost_analytics(db, current_user.organization_id)


@router.get("/insights", response_model=list[Insight])
def analytics_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
) -> list[Insight]:
    return analytics_service.insights(db, current_user.organization_id)


@router.get("/reports", response_model=AnalyticsReport)
def analytics_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("analytics.view")),
    period: str = Query(default="weekly", pattern="^(daily|weekly|monthly|quarterly|annual)$"),
) -> AnalyticsReport:
    return analytics_service.report(db, current_user.organization_id, period)
