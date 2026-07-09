"""Cross-cutting HTTP middleware (Phase 4.2.2.3.5 §13, §15, §16, §23).

Two concerns that must apply to *every* response, including error responses and
routes outside the identity package:

* **Request correlation (§15)** — every request gets a stable request id. A caller
  may supply one via the ``X-Request-ID`` header (so a browser/proxy trace ties to
  our logs); otherwise we mint a UUID4. It is stored on ``request.state.request_id``
  so the identity error envelope (``app.identity.errors``) and any handler can read
  it, and echoed back on the response so the caller can quote it in a bug report.

* **Security headers (§16, §23)** — a browser fetching this JSON API should be told,
  on every response, not to sniff content types, not to be framed, to leak no
  referrer, and to run under a deny-by-default CSP. These are cheap, universal and
  belong at the edge rather than in each route.

Both are pure ASGI-level concerns and deliberately hold no per-request state beyond
``request.state``; they are safe to add unconditionally and are individually
toggle-able via settings for deployments that terminate these at a reverse proxy.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every request/response (§15).

    Reads the configured header if the client sent one (trimmed, length-capped to
    keep a hostile client from stuffing the log line), otherwise generates a UUID4.
    """

    _MAX_INBOUND_LEN = 128

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        header = settings.REQUEST_ID_HEADER
        incoming = request.headers.get(header)
        request_id = incoming.strip()[: self._MAX_INBOUND_LEN] if incoming else ""
        if not request_id:
            request_id = str(uuid.uuid4())
        # Expose to downstream handlers (the identity error envelope reads this).
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[header] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply standard browser security headers to every response (§16, §23)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        # ``setdefault`` so a route that deliberately sets a different value (e.g. a
        # future HTML docs page needing a looser CSP) is never clobbered.
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", settings.SECURITY_REFERRER_POLICY)
        headers.setdefault("Content-Security-Policy", settings.SECURITY_CSP)
        headers.setdefault("Permissions-Policy", settings.SECURITY_PERMISSIONS_POLICY)
        if settings.SECURITY_HSTS_ENABLED:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.SECURITY_HSTS_MAX_AGE}; includeSubDomains",
            )
        return response


def install_http_middleware(app) -> None:
    """Register the cross-cutting middleware on the FastAPI app.

    Order matters. Starlette runs middleware in reverse registration order on the
    way *in*, so the LAST added runs first. We add security headers last so it is
    outermost — it therefore wraps the response even when an inner middleware or
    handler raises, and the request-context id is available before any handler runs.
    """
    if settings.REQUEST_ID_HEADER:
        app.add_middleware(RequestContextMiddleware)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware)
