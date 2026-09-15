"""Phase 5.8 (M5.8) - Enterprise Agent Command Center: the backend half.

A sibling package (not a child of ``app.runtime`` / ``app.posture`` /
``app.threat`` / ``app.bridge``), and a deliberately tiny one. The command
center is a **frontend** phase; this package exists only because two of its
views cannot be assembled from existing endpoints without doing arithmetic in
the browser over tens of thousands of rows.

The three sentences that govern it:

  * **It decides nothing and enforces nothing.** Read-only: no POST, PUT,
    PATCH or DELETE, asserted structurally. Every action the command center
    offers dispatches to the 5.1-5.7 endpoint that already owns it.

  * **It never forms a second opinion.** The posture score comes from 5.5's
    ``PostureSummaryService``; "is this agent shadow, and why" from 5.5's
    ``ShadowAgentService``; an agent's enforcement mode and reach from 5.7's
    ``app.bridge.modes``. Aggregating authoritative rows is not a new
    authority - recomputing them would be.

  * **It reports "you cannot see this" differently from "there is nothing".**
    Each estate section is probed against its own domain permission through the
    real ``AuthorizationGateway``, and a section the caller cannot read comes
    back ``visible: false``, never as a zero that would read as "all clear".
"""
