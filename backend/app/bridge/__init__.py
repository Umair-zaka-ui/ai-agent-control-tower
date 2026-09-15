"""Phase 5.7 (M5.7) - External Agent Governance Bridge.

A sibling package (not a child of ``app.runtime`` / ``app.threat`` /
``app.posture``). This is where ACT governs agents it does not run -- and the
whole phase turns on doing that **honestly**.

The five sentences that govern every module here:

  * **Every mode means exactly what it says.** ``OBSERVED`` sees and enforces
    nothing. ``ADVISORY`` evaluates policy and recommends, and enforces
    nothing. ``GATEWAY_ENFORCED`` authorizes or denies the capability calls
    that route *through ACT*, and reaches nothing else. ``NATIVE_ENFORCED``
    is the M1-M4 platform: ACT runs the agent, and the 4.3 engine and the kill
    switch apply. ACT never says "we govern this agent" when what it governs
    is that agent's boundary calls.

  * **The strongest mode is not writable.** ``NATIVE_ENFORCED`` is excluded
    from ``agents.external_enforcement_mode``'s CHECK constraint and is
    derived from ``control_state == 'GOVERNED'`` -- the same single signal
    Phase 5.6's truthful-containment gate reads. No row, and no code path in
    this package, can claim full enforcement. It has to be true.

  * **The gateway is a boundary, not a second authorizer.**
    ``CapabilityBoundary`` asks the existing ``AuthorizationGateway``
    (``authorize_agent``), reads the existing Phase 4.3 policies and prices
    against the existing Phase 4.4 budgets. A grant's scope only ever
    *narrows* what those authorities allow; it grants nothing.

  * **An external identity never becomes an internal one.** Authentication is
    a signed request against a scoped, expiring, revocable, replay-protected
    grant. No ``users`` row, no role, no session -- federation was rejected for
    exactly this reason (it provisions internal principals). There is no
    bypass: every capability call authorizes through the gateway.

  * **ACT does not proxy everything.** One declared governed capability ships
    (``http_tool.invoke``, dispatched through M1's egress guard). There is no
    catch-all route and no pass-through path, because ACT cannot truthfully
    promise to govern traffic it is not in the path of. A broad catalog and an
    external-agent SDK are deferred.

Transaction discipline: commit-before-dispatch, always. The boundary decides,
records and commits *before* the downstream call, and no statement in this
package takes ``FOR UPDATE``. See ``app/bridge/gateway.py``,
``docs/bridge/enforcement-modes.md`` and ADR-0021.
"""
