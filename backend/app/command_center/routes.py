"""Phase 5.8 (M5.8) - the Enterprise Agent Command Center's two read-only
aggregation endpoints, under ``/api/v1/command-center``.

**Read-only, and structurally so.** There is no POST, PUT, PATCH or DELETE in
this module, and there never should be: every action the command center offers
dispatches to the endpoint that already owns it - 5.1 claim/control-state, 5.5
and 5.6 finding lifecycles, 5.6 containment, 5.7 mode and grant revocation.
Each of those already authorizes, isolates by tenant, enforces idempotency,
writes its own audit and applies the truthful-reach rules. Adding a write here
would be a second door into logic that already has one. ``test_ac12_*`` asserts
the absence over the route table.

**Why two endpoints and not zero.** Everything else the center renders comes
from an endpoint 5.1-5.7 already built, composed client-side by react-query -
which is orchestration, not logic. These two cannot be: an estate count over
tens of thousands of agents cannot be assembled from a 500-row page without
counting in the browser, and an inventory row's enforcement mode would
otherwise cost one request per row. Both are ``COUNT``/``GROUP BY`` plus calls
into the services that already own the answers (5.5's posture and shadow, 5.7's
mode derivation). Phase 4.9 made the same narrow addition for the same reason.

**Authorization.** ``agent.view`` gates the request, because both endpoints are
fundamentally about agents. Every *other* domain the estate touches is probed
separately against its own permission, and a section the caller cannot see is
returned as ``visible: false`` rather than as zero - see
``CommandCenterService`` for why that distinction is the honest one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.command_center.service import CommandCenterService
from app.models.user import User

router = APIRouter(prefix="/api/v1/command-center", tags=["command-center"])

_VIEW = "agent.view"


@router.get("/estate")
def estate(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """The AI estate in one request: how many agents there are, how many ACT
    actually governs, how many are shadow, and what the posture, threat,
    external-governance, graph and cost pictures look like.

    Sections the caller lacks permission for come back ``visible: false`` with
    the permission named - never as a zero that would read as "all clear".
    """
    return CommandCenterService(db).estate(actor)


@router.get("/agents")
def inventory(
    control_state: str | None = Query(default=None),
    origin_category: str | None = Query(default=None),
    enforcement_mode: str | None = Query(default=None),
    shadow_only: bool = Query(default=False),
    query: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """One page of the inventory, each row carrying the truthful-affordance
    signal (``enforcement_mode``, ``reaches_agent_execution``,
    ``reaches_boundary_calls``, and the exact ``display``/``limits`` sentences
    5.7 permits) plus its shadow conditions.

    The signal ships with the row on purpose: it is what the UI renders
    affordances from, and computing it here - with 5.7's own functions - is
    what stops the browser forming a second opinion about what ACT can do.
    """
    return CommandCenterService(db).inventory(
        actor, control_state=control_state, origin_category=origin_category,
        enforcement_mode=enforcement_mode, shadow_only=shadow_only, query=query,
        page=page, page_size=page_size,
    )


__all__ = ["router"]
