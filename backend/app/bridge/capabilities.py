"""Phase 5.7 (M5.7) - the capability registry: the **specific, declared**
enterprise capabilities an external agent may route through ACT's boundary.

**This is the anti-proxy-everything spine.** ACT does not sit in front of the
external agent's model calls or its network traffic. There is no catch-all
route, no pass-through path, no "forward whatever you send" mode -- an
external agent can call exactly the keys in ``CAPABILITIES`` below, against
exactly the targets its grant scopes, and nothing else. A design that proxied
everything would be unscalable, would lock the customer in, and -- the reason
that actually matters here -- could not be *truthfully guaranteed*: ACT cannot
promise to see traffic it is not in the path of. ``test_ac06_*`` asserts this
structurally (no catch-all route, no HTTP client imported into this package
outside the declared M1 tool executor).

**One governed capability ships (the reference path).** ``http_tool.invoke``
dispatches a registered, published Phase-5.6a HTTP ``Tool`` through the M1
egress guard and executor -- a real enterprise capability making a real
outbound call. That is deliberate and is the §25A forward-compat position: a
broad catalog and an external-agent SDK are **deferred**, and one real path
proves the boundary better than ten declared ones would.

**Per-capability fail semantics honour the M4 §9 plane rule.** A *governance*
capability fails **closed**: if its authorization, policy or cost evaluation
cannot be completed, the call is denied and the denial is recorded. An
*observability* ingest fails **open**: a dropped event degrades evidence, it
never blocks or fakes anything. The two planes never share a code path -- the
boundary refuses to run an OBSERVABILITY capability through the governance
flow, and vice versa (``test_ac09_*``).
"""

from __future__ import annotations

from dataclasses import dataclass

#: §9 planes. GOVERNANCE decisions are authoritative and fail closed;
#: OBSERVABILITY is derived, non-authoritative, and fails open.
PLANES = ("GOVERNANCE", "OBSERVABILITY")


@dataclass(frozen=True)
class CapabilitySpec:
    """One capability an external agent may call through the boundary."""

    key: str
    display: str
    plane: str
    fail_mode: str
    #: The action string handed to ``AuthorizationGateway.authorize_agent``.
    #: It is a *constant per capability*, never assembled from caller input --
    #: an external agent cannot choose which permission it is checked against.
    authz_action: str
    #: Whether the call names a concrete target (a Tool id, here).
    requires_target: bool
    #: Whether Phase 4.4 can price this call at the boundary. Where False,
    #: the cost outcome is recorded ``NOT_MEASURABLE`` -- ACT does not invent
    #: a number for a call it cannot price.
    cost_measurable: bool
    limits: str


CAPABILITIES: dict[str, CapabilitySpec] = {
    "http_tool.invoke": CapabilitySpec(
        key="http_tool.invoke",
        display="Invoke a registered HTTP tool through ACT's governed boundary.",
        plane="GOVERNANCE",
        fail_mode="FAIL_CLOSED",
        authz_action="external_capability.http_tool.invoke",
        requires_target=True,
        cost_measurable=True,
        limits=("ACT authorizes and dispatches this one call. It does not observe or "
                "constrain any other call the agent makes by any other route."),
    ),
    "telemetry.ingest": CapabilitySpec(
        key="telemetry.ingest",
        display="Submit runtime events to ACT as evidence.",
        plane="OBSERVABILITY",
        fail_mode="FAIL_OPEN",
        # Recorded for completeness; the ingest path performs no authorization
        # decision that can gate anything, because it enforces nothing.
        authz_action="external_capability.telemetry.ingest",
        requires_target=False,
        cost_measurable=False,
        limits=("Evidence only. Ingesting an event enforces nothing and implies no "
                "control over the agent that sent it."),
    ),
}

#: The governed subset -- what the boundary will actually authorize and
#: dispatch. Exactly one entry by design (see the module docstring).
GOVERNED_CAPABILITIES: tuple[str, ...] = tuple(
    k for k, spec in CAPABILITIES.items() if spec.plane == "GOVERNANCE"
)


def get(key: str) -> CapabilitySpec | None:
    return CAPABILITIES.get(key)


__all__ = ["PLANES", "CapabilitySpec", "CAPABILITIES", "GOVERNED_CAPABILITIES", "get"]
