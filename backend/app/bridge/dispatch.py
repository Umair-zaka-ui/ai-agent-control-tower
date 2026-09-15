"""Phase 5.7 (M5.7) - the downstream half of the reference capability path.

Separated from ``gateway.py`` on purpose. Everything in this module runs
**after** the boundary has decided and committed, with no transaction open and
no lock held -- keeping it in its own file makes that boundary visible and
makes ``test_ac08_*``'s AST assertion (no ORM write, no ``with_for_update``,
no session use of any kind in the dispatch path) trivially checkable.

The dispatch reuses Phase 5.6a's ``execute_http_tool`` and its egress guard
unchanged: allowlisted hosts, DNS-pinned connections, no auto-followed
redirects, a response-size cap and a timeout. An external agent calling
through ACT's boundary gets exactly the egress control a native agent's tool
call gets -- ACT does not open a weaker path for a caller it trusts less.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.runtime import Tool


@dataclass(frozen=True)
class DispatchResult:
    status: str          # DISPATCHED / DISPATCH_FAILED
    detail: dict[str, Any]
    http_status: int | None = None


def dispatch_http_tool(tool: Tool, params: dict | None) -> DispatchResult:
    """Execute one registered HTTP tool. Never raises.

    Every failure -- an egress denial, a timeout, an oversized response -- is
    returned as a ``DISPATCH_FAILED`` result for the caller to record. A
    failed dispatch is a truthful record of a call ACT allowed and the
    downstream system did not complete; it is never reported as a success, and
    it never retroactively changes the boundary's ALLOW into a DENY (ACT did
    allow it -- pretending otherwise would misrepresent the decision).
    """
    from app.runtime.tools.egress_guard import DEFAULT_MAX_REDIRECTS, EgressPolicy
    from app.runtime.tools.http_executor import (
        DEFAULT_MAX_RESPONSE_BYTES,
        DEFAULT_TIMEOUT_SECONDS,
        execute_http_tool,
    )

    http_config = tool.http_config or {}
    if not http_config.get("allowed_hosts"):
        return DispatchResult(
            status="DISPATCH_FAILED",
            detail={"success": False, "error": "TOOL_HAS_NO_EGRESS_ALLOWLIST"},
        )

    policy = EgressPolicy(
        allowed_hosts=frozenset(http_config.get("allowed_hosts") or ()),
        allow_plaintext_http=bool(http_config.get("allow_plaintext_http", False)),
        local_dev_hosts=frozenset(http_config.get("local_dev_hosts") or ()),
        max_redirects=int(http_config.get("max_redirects", DEFAULT_MAX_REDIRECTS)),
    )
    params = params or {}
    # The method comes from the tool's own declaration, never from the
    # caller's parameters -- the same ACT-TLX-FR-010 rule that stops model
    # output smuggling a DELETE stops an external agent doing it.
    method = http_config.get("method") or "POST"
    try:
        result = execute_http_tool(
            method=method,
            base_url=tool.endpoint_reference or "",
            path=params.get("path") if isinstance(params, dict) else None,
            query=params.get("query") if isinstance(params, dict) else None,
            json_body=params.get("body") if isinstance(params, dict) else None,
            policy=policy,
            sensitive_headers=frozenset(http_config.get("sensitive_headers") or ()),
            sensitive_body_fields=frozenset(http_config.get("sensitive_body_fields") or ()),
            max_response_bytes=int(http_config.get("max_response_bytes",
                                                  DEFAULT_MAX_RESPONSE_BYTES)),
            timeout_seconds=float(http_config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        )
    except Exception as exc:  # noqa: BLE001 -- a dispatch failure is data, not an exception
        return DispatchResult(status="DISPATCH_FAILED",
                              detail={"success": False, "error": type(exc).__name__})

    if not result.success:
        return DispatchResult(
            status="DISPATCH_FAILED",
            detail={"success": False, "status": result.status,
                    "error": result.error or "EGRESS_DENIED",
                    "egress_reason": getattr(result.egress_decision, "reason", None)},
            http_status=result.status,
        )
    return DispatchResult(status="DISPATCHED",
                          detail={"success": True, "status": result.status},
                          http_status=result.status)


__all__ = ["DispatchResult", "dispatch_http_tool"]
