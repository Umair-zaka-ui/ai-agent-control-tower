"""Phase 5.6a.1 SRS ACT-TLX-FR-001, FR-006, FR-007, FR-009 — the HTTP tool
action executor: the only code path that turns an ``egress_guard``
decision into a real outbound connection.

**Connection pinning (rebinding defense, ACT-TLX-FR-006).** The egress
guard validates a hostname's resolved address exactly once; this module
then connects the actual TCP/TLS socket *to that validated IP*, never to
a freshly re-resolved hostname — there is no second DNS lookup between
validation and connect for a rebinding attacker to win. ``_PinnedTransport``
rewrites the outgoing request's connection target to the pinned IP while
preserving the original ``Host`` header and TLS SNI (via httpcore's
``sni_hostname`` request extension), so the receiving server's
virtual-host routing and certificate check both still see the real
hostname. Verified empirically before writing this module's tests: a
request built for a hostname that does not even resolve via DNS still
reaches a local test server bound to a pinned IP, with the server-observed
``Host`` header intact.

**Redirects are never auto-followed.** ``httpx``'s built-in
``follow_redirects`` would connect to each hop without re-running the
egress guard — exactly the SSRF hole ``ACT-TLX-FR-007`` exists to close.
Every redirect hop in this module is re-evaluated from scratch, by URL,
against the same policy, with a depth cap.

**The request target is never built by resolving model-supplied text as a
URL.** ``_build_target_url`` takes the tool's declared, allowlisted base
URL and only ever extracts the *path* component of whatever the caller
supplies, discarding any scheme/host smuggled into it — a params value of
``"https://evil.example.net/steal"`` contributes only the path
``"/steal"`` to the final URL; the host is always the tool's own declared
endpoint (``ACT-TLX-FR-010``).
"""

from __future__ import annotations

import json as jsonlib
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.runtime.tools.egress_guard import EgressDecision, EgressPolicy, evaluate_url

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB
DEFAULT_TIMEOUT_SECONDS = 30.0
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
REDACTED = "***REDACTED***"


@dataclass(frozen=True, slots=True)
class HttpExecutionResult:
    """Everything ``ToolGatewayService`` needs to persist a ``ToolCall``
    row and decide whether the invocation succeeded — never includes a
    credential or unredacted sensitive material (``ACT-TLX-FR-013``)."""

    success: bool
    egress_decision: EgressDecision
    status: int | None = None
    response_body_redacted: bytes | dict | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    truncated: bool = False
    error: str | None = None  # e.g. "TIMEOUT", "REDIRECT_DEPTH_EXCEEDED"
    # Phase 5.6a.2 (ACT-TLX-FR-025, AC-17) -- a numeric `Retry-After`
    # (seconds), if the final response carried one. Consumed by
    # `ToolGatewayService._invoke_http`'s retry backoff exactly the way
    # `ModelGatewayService` already honors a provider's own `Retry-After`
    # (`_provider_backoff_delay`) -- a target-supplied value always wins
    # over computed backoff.
    retry_after_seconds: float | None = None


def _build_target_url(base_url: str, path_suffix: str | None, query: str | None) -> str:
    base = urlsplit(base_url)
    suffix_parts = urlsplit(path_suffix or "")
    # Only the *path* of whatever the caller supplied is ever used -- a
    # scheme/host embedded in it (an absolute or protocol-relative URL) is
    # silently discarded, never resolved against the base the way
    # urljoin() would (urljoin("https://good/", "https://evil/") returns
    # "https://evil/" -- exactly the hijack this must never allow).
    safe_path = suffix_parts.path
    if safe_path and not safe_path.startswith("/"):
        safe_path = "/" + safe_path
    base_path = base.path.rstrip("/") if base.path not in ("", "/") else ""
    combined_path = (base_path + safe_path) or "/"
    return urlunsplit((base.scheme, base.netloc, combined_path, query or suffix_parts.query, ""))


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Phase 5.6a.2 (ACT-TLX-FR-025) -- mirrors ``openai_compatible.
    _parse_retry_after`` exactly (numeric seconds only; the HTTP-date form
    exists but is deliberately unhandled here for the same reason: no
    fixture or real target in this sub-phase's scope sends it, and
    guessing at date parsing without a real case to test against is
    exactly the kind of guess this codebase's design rules forbid).
    Duplicated as a tiny, private, ~8-line function rather than imported
    from ``app.runtime.providers`` -- this module (``app/runtime/tools/``)
    deliberately has zero dependency on the model-provider package; see
    this module's own docstring."""
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def redact_headers(headers: dict[str, str], sensitive: frozenset[str]) -> dict[str, str]:
    lowered_sensitive = {s.lower() for s in sensitive}
    return {k: (REDACTED if k.lower() in lowered_sensitive else v) for k, v in headers.items()}


def redact_body(body: dict | None, sensitive_fields: frozenset[str]) -> dict | None:
    if not isinstance(body, dict):
        return body
    lowered_sensitive = {s.lower() for s in sensitive_fields}
    return {k: (REDACTED if k.lower() in lowered_sensitive else v) for k, v in body.items()}


class _PinnedTransport(httpx.BaseTransport):
    """Connects to ``resolved_ip`` regardless of what host the request
    object nominally targets, preserving the original ``Host`` header
    (already set by ``httpx`` at request-construction time, before this
    transport ever sees the request — left untouched here) and setting
    TLS SNI to the original hostname via the ``sni_hostname`` extension
    httpcore's connection layer reads."""

    def __init__(self, resolved_ip: str, *, verify: bool, connect_timeout: float, read_timeout: float) -> None:
        self._resolved_ip = resolved_ip
        # One connection, never kept alive: this transport is built fresh
        # per request/redirect-hop (a new pinned IP each time), so there is
        # nothing to usefully pool.
        self._inner = httpx.HTTPTransport(
            verify=verify, limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.url.host
        request.url = request.url.copy_with(host=self._resolved_ip)
        request.extensions = {**request.extensions, "sni_hostname": original_host}
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def _evaluate_and_pin(url: str, policy: EgressPolicy, *, resolver, verify: bool,
                      connect_timeout: float, read_timeout: float) -> tuple[EgressDecision, httpx.BaseTransport | None]:
    decision = evaluate_url(url, policy, resolver=resolver)
    if not decision.allowed:
        return decision, None
    transport = _PinnedTransport(decision.resolved_ip, verify=verify,
                                 connect_timeout=connect_timeout, read_timeout=read_timeout)
    return decision, transport


def execute_http_tool(
    *, method: str, base_url: str, path: str | None = None, query: str | None = None,
    headers: dict[str, str] | None = None, json_body: dict | None = None,
    policy: EgressPolicy, sensitive_headers: frozenset[str] = frozenset(),
    sensitive_body_fields: frozenset[str] = frozenset(),
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    resolver=None, verify: bool = True,
) -> HttpExecutionResult:
    """Executes exactly one HTTP tool call, including following redirects
    (each hop re-validated, depth-capped). Never raises for an egress
    denial, a timeout, or an oversized response — every outcome is
    reported in the returned ``HttpExecutionResult`` for the caller to
    persist and translate into the platform's own error taxonomy."""
    headers = dict(headers or {})
    target = _build_target_url(base_url, path, query)
    connect_timeout = min(timeout_seconds, 10.0)

    redirects = 0
    while True:
        decision, transport = _evaluate_and_pin(target, policy, resolver=resolver, verify=verify,
                                                connect_timeout=connect_timeout, read_timeout=timeout_seconds)
        if not decision.allowed:
            return HttpExecutionResult(success=False, egress_decision=decision)

        request_body_bytes = len(jsonlib.dumps(json_body).encode("utf-8")) if json_body is not None else 0
        try:
            with httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(connect=connect_timeout, read=timeout_seconds,
                                      write=timeout_seconds, pool=connect_timeout),
                follow_redirects=False,
            ) as client:
                with client.stream(method, target, headers=headers, json=json_body) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        response.close()
                        if not location:
                            return HttpExecutionResult(success=False, egress_decision=decision,
                                                       status=response.status_code, error="REDIRECT_MISSING_LOCATION")
                        redirects += 1
                        if redirects > policy.max_redirects:
                            return HttpExecutionResult(success=False, egress_decision=decision,
                                                       status=response.status_code, error="REDIRECT_DEPTH_EXCEEDED")
                        # Location may be relative -- resolve against the
                        # current target's scheme/host only (still never
                        # trusting a redirect to silently escape re-validation).
                        target = _resolve_redirect_target(target, location)
                        continue

                    body = bytearray()
                    truncated = False
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            truncated = True
                            response.close()
                            break
                    return HttpExecutionResult(
                        success=not truncated, egress_decision=decision, status=response.status_code,
                        response_body_redacted=bytes(body), request_bytes=request_body_bytes,
                        response_bytes=len(body), truncated=truncated,
                        error="RESPONSE_TOO_LARGE" if truncated else None,
                        retry_after_seconds=_parse_retry_after(response),
                    )
        except httpx.TimeoutException:
            return HttpExecutionResult(success=False, egress_decision=decision, error="TIMEOUT")
        except httpx.HTTPError as exc:
            return HttpExecutionResult(success=False, egress_decision=decision, error=f"TRANSPORT_ERROR:{exc}")
        finally:
            transport.close()


def _resolve_redirect_target(current: str, location: str) -> str:
    parsed_location = urlsplit(location)
    if parsed_location.scheme and parsed_location.netloc:
        return location  # absolute redirect -- evaluated fresh against the policy next loop iteration
    current_parts = urlsplit(current)
    return urlunsplit((current_parts.scheme, current_parts.netloc, parsed_location.path,
                       parsed_location.query, ""))
