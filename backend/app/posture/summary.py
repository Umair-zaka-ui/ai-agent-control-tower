"""Phase 5.5 (M5.5) - ``PostureSummaryService``: a deterministic, versioned,
reconstructable posture aggregate.

**No opaque score.** The number is a fixed weighted sum of the open findings
by severity. The response carries the formula, the weights, the ruleset
version and the per-rule contributions - a CISO can see exactly which
findings drove the number and, comparing two summaries, exactly why it
changed. There is no ML and nothing stored: the summary is recomputed from
``posture_findings`` every call (ADR-0008 discipline - the aggregate is a
view over the evidence, never a second copy of it).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.posture import PostureFinding
from app.posture.rules import POSTURE_RULESET_VERSION, RULES_BY_ID, SHADOW_RULE_IDS

#: Fixed, versioned weights. A change here is a ruleset-version bump.
SEVERITY_WEIGHTS: dict[str, int] = {"CRITICAL": 10, "HIGH": 5, "WARNING": 2, "INFO": 1}

#: Deterministic grade bands over the weighted score (lower is better).
_GRADE_BANDS: tuple[tuple[int, str], ...] = (
    (0, "A"), (10, "B"), (25, "C"), (50, "D"), (100, "F"),
)


def _grade(score: int) -> str:
    grade = "F"
    for threshold, letter in _GRADE_BANDS:
        if score >= threshold:
            grade = letter
    return grade


class PostureSummaryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summarize(self, organization_id: uuid.UUID) -> dict:
        rows = self.db.execute(
            select(
                PostureFinding.rule_id,
                PostureFinding.severity,
                func.count(PostureFinding.id),
            )
            .where(
                PostureFinding.organization_id == organization_id,
                PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
                PostureFinding.outcome == "FINDING",
            )
            .group_by(PostureFinding.rule_id, PostureFinding.severity)
        ).all()

        by_severity: dict[str, int] = {s: 0 for s in SEVERITY_WEIGHTS}
        by_rule: dict[str, dict] = {}
        score = 0
        for rule_id, severity, count in rows:
            count = int(count)
            weight = SEVERITY_WEIGHTS.get(severity, 1)
            subtotal = weight * count
            score += subtotal
            by_severity[severity] = by_severity.get(severity, 0) + count
            entry = by_rule.setdefault(
                rule_id,
                {"rule_id": rule_id,
                 "control_id": RULES_BY_ID[rule_id].control_id if rule_id in RULES_BY_ID else None,
                 "count": 0, "weight": weight, "subtotal": 0,
                 "shadow_class": rule_id in SHADOW_RULE_IDS},
            )
            entry["count"] += count
            entry["subtotal"] += subtotal

        insufficient = int(
            self.db.execute(
                select(func.count(PostureFinding.id)).where(
                    PostureFinding.organization_id == organization_id,
                    PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
                    PostureFinding.outcome == "INSUFFICIENT_DATA",
                )
            ).scalar()
            or 0
        )
        shadow_agents = int(
            self.db.execute(
                select(func.count(func.distinct(PostureFinding.subject_id))).where(
                    PostureFinding.organization_id == organization_id,
                    PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
                    PostureFinding.outcome == "FINDING",
                    PostureFinding.rule_id.in_(tuple(SHADOW_RULE_IDS)),
                )
            ).scalar()
            or 0
        )

        return {
            "organization_id": str(organization_id),
            "as_of": datetime.now(timezone.utc).isoformat(),
            "ruleset_version": POSTURE_RULESET_VERSION,
            "score": score,
            "grade": _grade(score),
            "formula": "score = sum(severity_weight * open_finding_count) over open FINDING findings",
            "severity_weights": dict(SEVERITY_WEIGHTS),
            "grade_bands": [{"min_score": t, "grade": g} for t, g in _GRADE_BANDS],
            "open_findings_by_severity": by_severity,
            "total_open_findings": sum(by_severity.values()),
            "insufficient_data_open": insufficient,
            "shadow_agents": shadow_agents,
            "contributions": sorted(
                by_rule.values(), key=lambda e: (-e["subtotal"], e["rule_id"])
            ),
            "reconstructable": (
                "Recompute: multiply each rule's open FINDING count by its severity weight and sum. "
                "INSUFFICIENT_DATA and RESOLVED/SUPPRESSED findings are excluded by construction."
            ),
        }


__all__ = ["PostureSummaryService", "SEVERITY_WEIGHTS"]
