"""Phase 2.1.4 SRS ACT-INT-FR-066 — the only outbound network primitive the
SDK surface exposes.

A connector author never imports ``httpx``/``requests``/``urllib.request``
to reach a real endpoint. The SDK offers exactly one network primitive —
``GovernedHttpClient`` — a thin, connector-facing wrapper over the exact
SSRF-hardened path Milestone 1's own tools already use:
``app.runtime.tools.egress_guard``/``http_executor``, reused directly, not
reimplemented (the build prompt's own "the egress guard authors inherit,
never re-implement"). A request to a host the connector was not
constructed with is denied — by the allowlist check alone, before any DNS
lookup or socket is ever opened — exactly the same fail-closed guarantee a
first-party tool call already gets (``ACT-TLX-FR-004``..``010``).

**Why construction-time, not call-time, host declaration.** ``allowed_hosts``
is fixed when a ``GovernedHttpClient`` is built, never accepted as a
per-call argument to ``request``/``evaluate``. This is deliberate
containment, not an oversight (``ACT-INT-FR-066``, AC-11): a connector's
own code cannot widen what it may reach at the moment it makes a call — it
can only ever call out to what it declared when it built the client, which
in every intended usage is derived from the connector instance's own
configuration (the same shape ``MockConnector``'s ``endpoint`` or this
sub-phase's worked example's ``webhook_url`` already is)."""

from __future__ import annotations

from typing import Callable, Mapping

from app.runtime.tools.egress_guard import EgressDecision, EgressPolicy, evaluate_url
from app.runtime.tools.http_executor import HttpExecutionResult, execute_http_tool

Resolver = Callable[[str], list[str]]


class GovernedHttpClient:
    """Bound, at construction, to one connector's own declared set of
    reachable hosts. Offers two methods, both fail-closed and neither
    accepting a wider host set than the client was built with:

    - ``evaluate`` — a pure, offline policy check (no socket ever opened):
      denies immediately on an unlisted host via the allowlist rule alone,
      before any DNS resolution is attempted. This is what makes AC-11
      ("a call to an undeclared host is denied") verifiable without any
      live network or mocked transport.
    - ``request`` — performs the real call (only once ``evaluate`` would
      allow it), through the identical connection-pinning, redirect
      re-validation and response-size-capping path a first-party tool call
      already goes through."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str] | set[str] | tuple[str, ...],
        allow_plaintext_http: bool = False,
        local_dev_hosts: frozenset[str] | set[str] | tuple[str, ...] = frozenset(),
        max_redirects: int = 5,
    ) -> None:
        self._policy = EgressPolicy(
            allowed_hosts=frozenset(allowed_hosts),
            allow_plaintext_http=allow_plaintext_http,
            local_dev_hosts=frozenset(local_dev_hosts),
            max_redirects=max_redirects,
        )

    def evaluate(self, url: str, *, resolver: Resolver | None = None) -> EgressDecision:
        """Whether ``url`` would be permitted, with no network I/O of its
        own beyond an injectable ``resolver`` (real DNS by default) — an
        author's own tests, and this sub-phase's own governance tests, use
        this to prove denial/allowance deterministically and offline."""
        return evaluate_url(url, self._policy, resolver=resolver)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: dict | None = None,
        query: str | None = None,
        timeout_seconds: float = 30.0,
        resolver: Resolver | None = None,
    ) -> HttpExecutionResult:
        """Performs the call. Never raises for an egress denial — the
        returned ``HttpExecutionResult.egress_decision`` reports it, the
        same contract ``execute_http_tool`` already gives first-party
        tools, so a connector author handles a denial the same way this
        platform's own tool executor does.

        ``query`` — Phase 2.2.1 addition, discovered while building the
        REST connector (``ACT-INT-FR-104``): ``execute_http_tool``'s own
        ``_build_target_url`` only ever honors a query string supplied
        through its dedicated ``query`` parameter — any query string
        embedded directly in ``url`` itself is silently dropped (it reads
        only ``base_url``'s scheme/netloc/path, never its query
        component). 2.1.4's worked example never surfaced this gap since
        it had no query parameters at all; a paginated REST endpoint does.
        Rather than have every caller learn this the hard way, ``query``
        is now a first-class, optional parameter here, forwarded straight
        through — pass an already-encoded query string (e.g.
        ``urllib.parse.urlencode(...)``); leave ``url`` itself query-free."""
        return execute_http_tool(
            method=method, base_url=url, query=query, headers=dict(headers or {}), json_body=json_body,
            policy=self._policy, timeout_seconds=timeout_seconds, resolver=resolver,
        )
