"""Phase 5.6a.1 SRS ACT-TLX-FR-001..013 — HTTP tool execution & egress control.

``egress_guard.py`` is the SSRF containment boundary: pure logic, no
network, no database, exhaustively unit-tested against every known
bypass technique. ``http_executor.py`` is the only caller that turns an
``EgressDecision`` into an actual outbound connection, pinned to the
address the guard validated.
"""

from __future__ import annotations
