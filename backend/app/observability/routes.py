"""Phase 4.2 -- the observability trace API (ACT-SRS-M4 §6, §15, §16, §28).

Mounted at ``/api/v1/observability``. **This is the governed-observability trace
surface**, deliberately distinct from the older `analytics` dashboards, which
aggregate the Phase 3 `agent_actions` table with flat cost estimates and have no
connection to `AgentExecution` at all (see REPO_STATE §9 on why they were not
rewired). Nothing here collides with them.

**Three properties hold on every route in this module, and each is tested:**

*Metadata only.* No endpoint returns a prompt, a tool argument, a tool result or
model output. That boundary is 4.8's to move, behind capture policy and
``runtime.trace.content.view``. It is enforced upstream in the read models
themselves -- neither the assembler nor the explorer reads a content column --
so it cannot be undone by a route change alone.

*Tenant-scoped.* Every query filters on the actor's organization before
anything else. A cross-tenant trace id is indistinguishable from one that does
not exist, which is §34's requirement: not merely refusing to read another
tenant's data, but refusing to confirm it exists.

*Read-only and non-gating.* These are ordinary indexed reads. Reading a trace --
including one that is still running -- never takes a lock, never writes, and
cannot affect the execution it describes (SRS §9).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.models.user import User
from app.observability.assembly import TraceAssembler
from app.observability.explorer import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TraceExplorer,
    TraceFilters,
    is_known_status,
)

router = APIRouter(prefix="/api/v1/observability", tags=["observability"])

# Phase 4.1 established that `runtime.telemetry.view` -- which already existed,
# and whose catalog description already read "View runtime telemetry and
# execution traces" -- is the permission for this. 4.2 reuses it rather than
# registering a synonym: two permission codes guarding one capability is how an
# authorization model starts drifting from what operators believe they granted.
# See this phase's report for the deviation from the build prompt's suggested
# `runtime.observability.view`.
_TRACE_VIEW = "runtime.telemetry.view"

# The stronger permission that will gate trace *content* in Phase 4.8. Named
# here for one reason only: so a reader of this module can see that the content
# boundary is deliberate and has an owner, rather than wondering whether it was
# forgotten. It is **not registered in the permission catalog and guards no
# route**, because a permission that guards nothing teaches operators it is safe
# to grant -- the same reasoning 4.1 used when it declined to register it.
_CONTENT_VIEW_RESERVED_FOR_4_8 = "runtime.trace.content.view"


@router.get("/traces")
def search_traces(
    trace_id: str | None = Query(default=None),
    execution_id: uuid.UUID | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
    agent_version_id: uuid.UUID | None = Query(default=None),
    deployment_id: uuid.UUID | None = Query(default=None),
    environment: str | None = Query(default=None),
    model: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    tool_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    error_code: str | None = Query(default=None),
    only_errors: bool = Query(default=False),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_permission(_TRACE_VIEW)),
    db: Session = Depends(get_db),
):
    """The trace explorer (M4-4.2-FR-010): find the execution you need.

    Bounded on three axes at once, because any one of them alone leaves a shape
    that is cheap on a small tenant and a table scan on a large one: the tenant
    predicate leads every plan, the result set is paginated to at most
    ``MAX_PAGE_SIZE``, and an absent time range defaults to a 30-day window
    rather than to "everything".

    Results are metadata -- identities, timings, status, cost and token counts.
    No content."""
    if not is_known_status(status):
        # Rejected rather than served as an empty page: an unrecognized status
        # is a typo or a client bug, and returning "no results" would look like
        # a true answer to a question that was never actually asked.
        raise IdentityError(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown execution status {status!r}.",
        )

    filters = TraceFilters(
        trace_id=trace_id, execution_id=execution_id, agent_id=agent_id,
        agent_version_id=agent_version_id, deployment_id=deployment_id,
        environment=environment, model=model, provider=provider, tool_id=tool_id,
        status=status, error_code=error_code, only_errors=only_errors,
        started_after=started_after, started_before=started_before,
    )
    page = TraceExplorer(db).search(actor.organization_id, filters,
                                    limit=limit, offset=offset)
    return page.as_dict()


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str,
              actor: User = Depends(require_permission(_TRACE_VIEW)),
              db: Session = Depends(get_db)):
    """One trace by its trace id (M4-4.2-FR-001).

    A trace id is either a caller-supplied ``correlation_id``, which may span
    several executions, or an execution's own primary key used as 4.1's derived
    fallback. Both resolve; the response is a list of assembled traces because
    the first case genuinely can be more than one.

    A trace belonging to another tenant returns ``TRACE_NOT_FOUND`` -- the same
    response as one that does not exist anywhere, so the two are
    indistinguishable (§34)."""
    explorer = TraceExplorer(db)
    executions = explorer.find_by_trace_id(actor.organization_id, trace_id)
    if not executions:
        raise IdentityError(ErrorCode.TRACE_NOT_FOUND, "Trace not found.")

    assembler = TraceAssembler(db)
    traces = [assembler.assemble(execution).as_dict() for execution in executions]
    return {"trace_id": trace_id, "executions": len(traces), "traces": traces}


@router.get("/executions/{execution_id}/trace")
def get_execution_trace(execution_id: uuid.UUID,
                        actor: User = Depends(require_permission(_TRACE_VIEW)),
                        db: Session = Depends(get_db)):
    """One execution's assembled trace (M4-4.2-FR-001..005).

    The canonical path for this. Phase 4.1 shipped the same capability at
    ``/api/v1/runtime/executions/{id}/trace`` before this prefix existed; that
    route is retained (its tests pin it, and removing a working endpoint to
    tidy a prefix is not worth breaking a caller over) and delegates to the
    same assembler, so the two cannot diverge. New callers should use this one.

    Metadata only, tenant-scoped, and safe to call against an in-flight
    execution -- a partial trace shows the nodes that have happened and omits
    the ones that have not, rather than inventing terminal state (AC-11)."""
    trace = TraceAssembler(db).for_execution(actor.organization_id, execution_id)
    if trace is None:
        raise IdentityError(ErrorCode.EXECUTION_NOT_FOUND, "Execution not found.")
    return trace.as_dict()
