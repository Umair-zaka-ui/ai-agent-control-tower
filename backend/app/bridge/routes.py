"""Phase 5.7 (M5.7) - the external governance bridge's HTTP surface, under
``/api/v1/bridge``.

Two kinds of endpoint live here and they authenticate completely differently,
which is the point:

  * **management** (``/agents/{id}/enforcement-mode``, ``/grants``, ``/calls``)
    -- an internal operator with a JWT, authorized by ``require_permission``
    through the existing ``AuthorizationGateway``. Issuing or revoking a grant
    needs ``external_grant.issue``: a **distinct, stronger** code that
    ``external_governance.view``/``.manage`` never imply, because it is what
    creates an outside party's ability to reach enterprise capability -- the
    same reasoning that made ``containment.execute`` its own code in 5.6.

  * **the boundary** (``/capability``, ``/events``) -- an agent *outside* ACT,
    authenticated by a signed request against a scoped grant. It presents no
    JWT, holds no session, and is never resolved to a ``User``. Every call it
    makes is authorized by ``AuthorizationGateway`` on the **agent** principal.

**There is exactly one governed capability endpoint and it is not a proxy.**
No route here takes a path parameter that is forwarded anywhere; there is no
catch-all, no ``{path:path}``, and no way to name a destination. A caller
names a *declared capability key* and a target its grant already scopes.
``test_ac06_*`` asserts that over the route table.

**Why the raw body is read in an async dependency.** The signature covers the
exact bytes received, not a re-serialization of a parsed model -- re-encoding
JSON before verifying is where signing schemes quietly break across languages.
Reading the body requires ``await``, but the handlers are synchronous so their
blocking database work stays on the threadpool rather than the event loop. An
async *dependency* feeding a sync *route* gives both.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.bridge import capabilities as caps
from app.bridge.gateway import CapabilityBoundary
from app.bridge.identity import (
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    SIGNATURE_SCHEME,
    ExternalGrantService,
)
from app.bridge.modes import effective_mode, reach_of
from app.bridge.observed import AdvisoryService, ObservedIngestService
from app.bridge.schemas import (
    AdvisoryResponse,
    CapabilityCallRequest,
    CapabilityCallResponse,
    EnforcementModeRead,
    EnforcementModeSet,
    GatewayCallRead,
    GrantCreate,
    GrantIssued,
    GrantRead,
    GrantRevoke,
    ObservedIngestRequest,
    ObservedIngestResponse,
)
from app.bridge.service import EnforcementModeService
from app.identity.errors import ErrorCode, IdentityError
from app.models.bridge import ExternalGatewayCall
from app.models.user import User

router = APIRouter(prefix="/api/v1/bridge", tags=["external-governance-bridge"])

_VIEW = "external_governance.view"
_MANAGE = "external_governance.manage"
_ISSUE = "external_grant.issue"

_SIGNING_INSTRUCTIONS = (
    "Sign every request: HMAC-SHA256 over "
    f"'{SIGNATURE_SCHEME}\\n<METHOD>\\n<path>\\n<unix-timestamp>\\n<nonce>\\n"
    "<sha256-hex-of-body>', hex-encoded, with this secret. Send it as "
    f"{HEADER_SIGNATURE}, with {HEADER_KEY_ID}, {HEADER_TIMESTAMP} and a fresh "
    f"{HEADER_NONCE} on each request. This secret is shown once and is not retrievable."
)


# --------------------------------------------------------------------------- #
# The signed-request envelope (the boundary's front door)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SignedRequest:
    key_id: str
    timestamp: str
    nonce: str
    signature: str
    method: str
    path: str
    body: bytes


async def signed_request(request: Request) -> SignedRequest:
    """Collect the signature envelope and the exact body bytes.

    Missing headers are not distinguished from a bad signature in the error
    the caller sees -- the service raises one generic message for every
    authentication failure so a prober learns nothing about which key_ids
    exist. The 422 here is only for a request that carries no envelope at all.
    """
    headers = request.headers
    key_id = headers.get(HEADER_KEY_ID)
    timestamp = headers.get(HEADER_TIMESTAMP)
    nonce = headers.get(HEADER_NONCE)
    signature = headers.get(HEADER_SIGNATURE)
    if not all((key_id, timestamp, nonce, signature)):
        raise IdentityError(
            ErrorCode.EXTERNAL_SIGNATURE_MISSING,
            f"This endpoint requires a signed request: {HEADER_KEY_ID}, {HEADER_TIMESTAMP}, "
            f"{HEADER_NONCE} and {HEADER_SIGNATURE}.",
        )
    return SignedRequest(
        key_id=key_id, timestamp=timestamp, nonce=nonce, signature=signature,
        method=request.method, path=request.url.path, body=await request.body(),
    )


def _rate_limit(db: Session, grant_key_id: str, limit: int) -> None:
    from app.identity.ratelimit.limiter import RateLimiter

    decision = RateLimiter(db).check(f"bridge:{grant_key_id}", limit=limit, window_seconds=60)
    if not decision.allowed:
        raise IdentityError(
            ErrorCode.EXTERNAL_RATE_LIMITED,
            f"This grant exceeded its rate limit of {limit} requests per minute.",
        )


# --------------------------------------------------------------------------- #
# Management — enforcement mode
# --------------------------------------------------------------------------- #
@router.get("/agents/{agent_id}/enforcement-mode", response_model=EnforcementModeRead)
def read_mode(agent_id: uuid.UUID,
              actor: User = Depends(require_permission(_VIEW)),
              db: Session = Depends(get_db)):
    return EnforcementModeService(db).read(actor, agent_id)


@router.put("/agents/{agent_id}/enforcement-mode", response_model=EnforcementModeRead)
def set_mode(agent_id: uuid.UUID, payload: EnforcementModeSet,
             actor: User = Depends(require_permission(_MANAGE)),
             db: Session = Depends(get_db)):
    """Set the *requested* mode. NATIVE_ENFORCED is not assignable here and
    the service says why -- it is derived from control_state, not declared."""
    return EnforcementModeService(db).set_mode(
        actor, agent_id, target_mode=payload.target_mode, reason=payload.reason)


@router.get("/modes", response_model=list[dict])
def list_modes(actor: User = Depends(require_permission(_VIEW))):
    """The four modes and, for each, exactly what ACT can and cannot do."""
    from app.bridge.modes import ENFORCEMENT_MODES, REACH

    return [{
        "mode": m,
        "display": REACH[m].display,
        "limits": REACH[m].limits,
        "reaches_boundary_calls": REACH[m].reaches_boundary_calls,
        "reaches_agent_execution": REACH[m].reaches_agent_execution,
        "assignable": m != "NATIVE_ENFORCED",
    } for m in ENFORCEMENT_MODES]


@router.get("/capabilities", response_model=list[dict])
def list_capabilities(actor: User = Depends(require_permission(_VIEW))):
    """The declared capabilities an external agent may route through ACT.

    Deliberately short. ACT governs these and does not proxy anything else; a
    broad catalog and an external-agent SDK are out of scope for this phase.
    """
    return [{
        "key": spec.key, "display": spec.display, "plane": spec.plane,
        "fail_mode": spec.fail_mode, "requires_target": spec.requires_target,
        "cost_measurable": spec.cost_measurable, "limits": spec.limits,
    } for spec in caps.CAPABILITIES.values()]


# --------------------------------------------------------------------------- #
# Management — grants
# --------------------------------------------------------------------------- #
@router.post("/agents/{agent_id}/grants", response_model=GrantIssued,
             status_code=status.HTTP_201_CREATED)
def issue_grant(agent_id: uuid.UUID, payload: GrantCreate,
                actor: User = Depends(require_permission(_ISSUE)),
                db: Session = Depends(get_db)):
    agent = EnforcementModeService(db).get_or_404(actor, agent_id)
    grant, secret = ExternalGrantService(db).issue(
        actor, agent, label=payload.label,
        scope=[e.model_dump() for e in payload.scope],
        expires_at=payload.expires_at,
        rate_limit_per_minute=payload.rate_limit_per_minute,
    )
    return GrantIssued(grant=GrantRead.model_validate(grant), secret=secret,
                       signature_scheme=SIGNATURE_SCHEME,
                       signing_instructions=_SIGNING_INSTRUCTIONS)


@router.get("/agents/{agent_id}/grants", response_model=list[GrantRead])
def list_grants(agent_id: uuid.UUID,
                actor: User = Depends(require_permission(_VIEW)),
                db: Session = Depends(get_db)):
    agent = EnforcementModeService(db).get_or_404(actor, agent_id)
    return ExternalGrantService(db).list_for_agent(actor, agent)


@router.post("/grants/{grant_id}/revoke", response_model=GrantRead)
def revoke_grant(grant_id: uuid.UUID, payload: GrantRevoke,
                 actor: User = Depends(require_permission(_ISSUE)),
                 db: Session = Depends(get_db)):
    """Revocation takes effect immediately: every boundary call re-reads the
    grant row, and nothing about a grant is cached anywhere."""
    return ExternalGrantService(db).revoke(actor, grant_id, reason=payload.reason)


# --------------------------------------------------------------------------- #
# Management — advisory + the decision record
# --------------------------------------------------------------------------- #
@router.post("/agents/{agent_id}/advisory", response_model=AdvisoryResponse)
def advisory(agent_id: uuid.UUID,
             actor: User = Depends(require_permission(_MANAGE)),
             db: Session = Depends(get_db)):
    agent = EnforcementModeService(db).get_or_404(actor, agent_id)
    rec = AdvisoryService(db).evaluate(actor, agent)
    return AdvisoryResponse(finding=rec.finding, detail=rec.detail,
                            enforcement_performed=False)


@router.get("/calls", response_model=list[GatewayCallRead])
def list_calls(agent_id: uuid.UUID | None = Query(default=None),
               outcome: str | None = Query(default=None),
               limit: int = Query(default=100, ge=1, le=500),
               actor: User = Depends(require_permission(_VIEW)),
               db: Session = Depends(get_db)):
    stmt = select(ExternalGatewayCall).where(
        ExternalGatewayCall.organization_id == actor.organization_id)
    if agent_id:
        stmt = stmt.where(ExternalGatewayCall.agent_id == agent_id)
    if outcome:
        stmt = stmt.where(ExternalGatewayCall.outcome == outcome)
    return list(db.execute(
        stmt.order_by(ExternalGatewayCall.created_at.desc()).limit(limit)).scalars())


# --------------------------------------------------------------------------- #
# The boundary — called by an agent OUTSIDE ACT, over a signed request
# --------------------------------------------------------------------------- #
@router.post("/capability", response_model=CapabilityCallResponse)
def call_capability(response: Response,
                    signed: SignedRequest = Depends(signed_request),
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    db: Session = Depends(get_db)):
    """One governed capability call, decided at ACT's boundary.

    The order below is the phase's transaction discipline and is not
    rearrangeable: rate limit, then verify (which consumes the nonce and
    commits, so a replay loses before any work), then decide and **commit**,
    and only then dispatch. No lock is held across the dispatch because no
    transaction is open across it.
    """
    import json as jsonlib

    grants = ExternalGrantService(db)
    # Resolve the grant's own limit before verifying, so an unauthenticated
    # flood is still bounded; a bad key_id falls back to a conservative bucket.
    from app.models.bridge import ExternalCapabilityGrant

    known = db.execute(select(ExternalCapabilityGrant).where(
        ExternalCapabilityGrant.key_id == signed.key_id)).scalars().first()
    _rate_limit(db, signed.key_id, known.rate_limit_per_minute if known else 60)

    identity = grants.verify(
        key_id=signed.key_id, timestamp=signed.timestamp, nonce=signed.nonce,
        signature=signed.signature, method=signed.method, path=signed.path,
        body=signed.body,
    )

    try:
        payload = CapabilityCallRequest.model_validate(jsonlib.loads(signed.body or b"{}"))
    except Exception as exc:  # noqa: BLE001
        raise IdentityError(ErrorCode.EXTERNAL_REQUEST_INVALID,
                            "Request body is not a valid capability call.") from exc

    boundary = CapabilityBoundary(db)
    decision = boundary.decide(
        identity, capability_key=payload.capability, target_ref=payload.target_ref,
        params=payload.params, request_id=None, idempotency_key=idempotency_key,
    )
    # --- the transaction is now committed and closed ---

    dispatch_status, dispatch_detail = "NOT_DISPATCHED", None
    if decision.allowed:
        dispatch_status, dispatch_detail = _dispatch(db, identity, decision)
        boundary.record_dispatch(decision.record_id, status=dispatch_status,
                                 detail=dispatch_detail)

    reach = reach_of(identity.agent)
    if not decision.allowed:
        response.status_code = status.HTTP_403_FORBIDDEN
    return CapabilityCallResponse(
        call_id=decision.record_id,
        outcome="ALLOWED" if decision.allowed else "DENIED",
        capability=payload.capability,
        enforcement_mode=effective_mode(identity.agent),
        enforcement_reach=reach.display,
        limits=reach.limits,
        denial_reason=decision.denial_reason,
        fail_mode=decision.fail_mode,
        dispatch_status=dispatch_status,
        dispatch_detail=dispatch_detail,
    )


def _dispatch(db: Session, identity, decision) -> tuple[str, dict | None]:
    """Resolve the target and dispatch. Runs with no transaction open.

    The tool row is read in its own short transaction *before* the call and
    nothing is held afterwards -- the read is a plain SELECT with no lock, and
    the dispatch itself touches no session at all (``app/bridge/dispatch.py``
    imports none).
    """
    from app.bridge.dispatch import dispatch_http_tool
    from app.models.runtime import Tool

    try:
        tool_id = uuid.UUID(str(decision.target_ref))
    except (TypeError, ValueError):
        return "DISPATCH_FAILED", {"success": False, "error": "TARGET_NOT_A_TOOL"}
    tool = db.get(Tool, tool_id)
    if tool is None or (tool.organization_id is not None
                        and tool.organization_id != identity.organization_id):
        # Tenant isolation at the dispatch hop too: a grant in one tenant can
        # never reach another tenant's tool, even if its scope named the id.
        return "DISPATCH_FAILED", {"success": False, "error": "TOOL_NOT_FOUND"}
    params = decision.dispatch_plan.get("params") or {}
    db.rollback()  # ensure nothing is open across the outbound call
    result = dispatch_http_tool(tool, params)
    return result.status, result.detail


@router.post("/events", response_model=ObservedIngestResponse,
             status_code=status.HTTP_202_ACCEPTED)
def ingest_events(signed: SignedRequest = Depends(signed_request),
                  db: Session = Depends(get_db)):
    """OBSERVED ingest. Fails **open**: a request that reaches here with a
    valid signature is accepted (202) even if every event is dropped, because
    evidence never gates anything. Authentication is still required -- fail-open
    is about the telemetry plane, not about who may write to it.
    """
    import json as jsonlib

    from app.models.bridge import ExternalCapabilityGrant

    known = db.execute(select(ExternalCapabilityGrant).where(
        ExternalCapabilityGrant.key_id == signed.key_id)).scalars().first()
    _rate_limit(db, signed.key_id, known.rate_limit_per_minute if known else 60)

    identity = ExternalGrantService(db).verify(
        key_id=signed.key_id, timestamp=signed.timestamp, nonce=signed.nonce,
        signature=signed.signature, method=signed.method, path=signed.path,
        body=signed.body,
    )
    # Fail-open governs how a *malformed or unstorable event* is treated, never
    # who may write one. A grant not scoped for evidence is refused here, before
    # anything is ingested.
    if not identity.scoped_for("telemetry.ingest", None):
        raise IdentityError(
            ErrorCode.EXTERNAL_SCOPE_DENIED,
            "This grant is not scoped for 'telemetry.ingest'.",
        )
    try:
        payload = ObservedIngestRequest.model_validate(jsonlib.loads(signed.body or b"{}"))
        events = [e.model_dump() for e in payload.events]
    except Exception:  # noqa: BLE001 -- §9: a malformed batch is dropped, not an error
        return ObservedIngestResponse(accepted=0, dropped=0, enforcement_performed=False)

    outcome = ObservedIngestService(db).ingest(identity.agent, events)
    return ObservedIngestResponse(accepted=outcome.accepted, dropped=outcome.dropped,
                                  enforcement_performed=False)


__all__ = ["router", "signed_request", "SignedRequest"]
