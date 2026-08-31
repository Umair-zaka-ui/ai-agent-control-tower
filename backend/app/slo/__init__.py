"""Phase 4.7 -- runtime service objectives (SLOs) and a first-class alert
lifecycle (ACT-SRS-M4 §3.6, §4.7, §18; Gates J and K).

**This is a discipline-of-restraint phase, and the line is one sentence: build
the signal, not the notification platform.** This package defines SLOs (an SLI,
a target, a window, an error budget), evaluates them deterministically with
INSUFFICIENT_DATA honesty, and turns a breach -- or a *significant* behavioral
finding from 4.5 -- into a durable, auditable alert with a real lifecycle
(OPEN → ACKNOWLEDGED → RESOLVED → SUPPRESSED). It does **not** send a Slack
message, an email, a PagerDuty page, or a webhook. Those are future integrations
that *consume* these records; a test walks the AST of this package and fails on
any delivery client (`smtplib`, `requests`, `httpx`, `slack`, `pagerduty`, ...).

**Three reuse anchors, none of them a new mechanism:**

1. **The 3.5 / 4.5 evaluation shape.** SLO evaluation is veto → sufficiency →
   objective comparison → budget math, deterministic and explainable: a breach
   states the SLI, the target, the window and the observed value, and an
   operator can recompute the verdict by hand. The shared state values
   (`INSUFFICIENT_DATA`, `UNKNOWN`) are spelled exactly as 3.5 and 4.5 spell
   them -- see :mod:`app.slo.states`.
2. **4.5's behavioral findings feed this lifecycle -- they are not a parallel
   concept.** A `behavioral_findings` row of significance (state `ANOMALOUS`)
   raises an alert that *references* it as evidence. `app/behavior` is not
   touched and knows nothing about alerts; the dependency runs one way,
   `app.slo` → `app.behavior`, visible in the import graph.
3. **The idempotent interim evaluate op** (like 4.5, 3.5, 3.7). One
   `POST /slos/evaluate` that Phase 3.8's scheduler can adopt as a
   registration. No scheduler is built here.

**An SLO breach / alert is a signal, never enforcement.** Nothing in this
package writes an execution's status, raises a governance stop, or reaches the
kill switch; Phase 4.3's engine remains the only thing that can stop an
execution. Emitting is non-gating (§9): an evaluation failure produces no
evaluation and no alert, and cannot affect any execution.
"""

from __future__ import annotations

from app.slo.alerts import AlertService
from app.slo.definitions import SLODefinitionError, SLOService
from app.slo.evaluator import SLOEvaluator
from app.slo.states import (
    AlertSeverity,
    AlertSource,
    AlertStatus,
    SLOState,
)

__all__ = [
    "AlertService",
    "SLOService",
    "SLODefinitionError",
    "SLOEvaluator",
    "SLOState",
    "AlertSeverity",
    "AlertSource",
    "AlertStatus",
]
