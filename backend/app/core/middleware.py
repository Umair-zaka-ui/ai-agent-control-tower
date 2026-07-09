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

import json
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap successful JSON API responses in the standard envelope (§5).

    ``{"success": true, "data": <original payload>, "meta": {request_id, timestamp}}``

    Scope is deliberately narrow so nothing else is disturbed:

    * only requests under ``/api`` (so ``/openapi.json``, ``/docs`` and ``/health``
      are untouched and Swagger keeps working),
    * only ``2xx`` responses (errors are already enveloped by the identity handler),
    * only ``application/json`` bodies (a CSV/file export streams through untouched),
    * never double-wraps a body that already looks enveloped.

    The correlation id is read from ``request.state.request_id`` (set by
    ``RequestContextMiddleware``, which sits outside this one), so success and error
    envelopes quote the same id.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if not settings.RESPONSE_ENVELOPE_ENABLED:
            return response
        if not request.url.path.startswith("/api"):
            return response
        if not (200 <= response.status_code < 300):
            return response
        if not response.headers.get("content-type", "").startswith("application/json"):
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        # Headers to carry over to the rebuilt response. Drop content-length (the new
        # body has a new length) and content-type (JSONResponse sets it); keep the
        # rest, e.g. CORS headers added by an inner middleware.
        passthrough = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-length", "content-type")
        }

        if not body:
            return Response(status_code=response.status_code, headers=passthrough)

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Content-Type lied; pass the bytes through unchanged rather than guess.
            return Response(
                content=body,
                status_code=response.status_code,
                headers=passthrough,
                media_type=response.headers.get("content-type"),
            )

        already_enveloped = (
            isinstance(payload, dict)
            and "success" in payload
            and ("data" in payload or "error" in payload)
        )
        if already_enveloped:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=passthrough,
                media_type="application/json",
            )

        enveloped = {
            "success": True,
            "data": payload,
            "meta": {
                "request_id": getattr(request.state, "request_id", None),
                "timestamp": _now_iso(),
            },
        }
        return JSONResponse(
            content=enveloped,
            status_code=response.status_code,
            headers=passthrough,
        )


def install_http_middleware(app) -> None:
    """Register the cross-cutting middleware on the FastAPI app.

    Order matters. ``add_middleware`` prepends, so the LAST added is outermost.
    Target nesting (outer → inner): SecurityHeaders → RequestContext → Envelope →
    (CORS) → router. That way the request id is set before the envelope reads it,
    and the security/correlation headers are (re)applied to the rebuilt enveloped
    response. Add innermost first:
    """
    if settings.RESPONSE_ENVELOPE_ENABLED:
        app.add_middleware(ResponseEnvelopeMiddleware)
    if settings.REQUEST_ID_HEADER:
        app.add_middleware(RequestContextMiddleware)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware)
