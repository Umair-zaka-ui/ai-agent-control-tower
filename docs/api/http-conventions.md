# HTTP API conventions & contract

_Phase 4.2.2.3.5 — Backend APIs, integration & release. This is the consolidated
contract for the Enterprise Identity Platform surface (`/api/v1/*`)._

## 1. Endpoint map (SRS §4)

Every capability the SRS §4 lists is implemented. A few live under a different,
already-stable path than the §4 sketch; those are called out as **[path]** below
rather than being duplicated — moving a shipped, tested, frontend-wired route only to
match a sketch would break clients for no functional gain.

| Group | Endpoint | Notes |
|-------|----------|-------|
| Auth | `POST /api/v1/auth/login` | Behind the adaptive rate limiter (4.2.2.3.4) |
| Auth | `POST /api/v1/auth/logout` | `{"all_devices": true}` performs "logout all" |
| Auth | `POST /api/v1/auth/refresh` | Rotating refresh-token family |
| Auth | `GET  /api/v1/auth/me` | Identity, roles, effective permissions |
| Registration | `POST /api/v1/auth/register`, `/register/self` | |
| Registration | `POST /api/v1/identity/invitations`, `/resend`, `/cancel` | **[path]** under `/identity` (admin, permission-gated) |
| Email | `POST /api/v1/auth/verify-email`, `/resend-verification` | |
| Email | `POST /api/v1/auth/change-email`, `/verify-new-email` | |
| Password | `POST /api/v1/security/change-password` | **[path]** under `/security` |
| Password | `POST /api/v1/auth/forgot-password`, `/reset-password` | |
| Password | `GET  /api/v1/security/password-policy` | **[path]** under `/security` |
| Sessions | `GET /api/v1/auth/sessions`, `GET …/{id}`, `DELETE …/{id}` | Revoke = soft (the row is the audit record) |
| Sessions | `POST /api/v1/auth/sessions/{id}/revoke`; `logout {all_devices}` | "logout-all" folded into `/logout` |
| Devices | `GET /api/v1/auth/devices`, `…/{id}/trust`, `…/{id}/block` | Blocking a device revokes its live sessions |
| Security | `GET /api/v1/security/login-attempts`, `/risk-events`, `/account-locks`, `/blocked-ips`, `/identity-protection-rules` | Permission `security.protection` |
| Security | `GET /api/v1/identity/security-events` | **[path]** the org-wide audit stream |
| Admin | `POST /api/v1/security/users/{id}/lock`, `/unlock` | **[path]** protection console |
| Admin | `POST /api/v1/security/admin/reset-password` | **[path]** issues a temporary password |
| Admin | `POST /api/v1/identity/users/{id}/activate`, `/suspend` | **[path]** = disable/enable |

Deliberately **not** built: a standalone `POST /auth/logout-all` and
`DELETE /auth/devices/{id}`. The first is fully covered by `logout {all_devices:true}`
(what the SPA already calls); the second has no consumer and devices are never hard
-deleted (they anchor session/audit history — "block" is the destructive action). Adding
either would be unreachable code, which this codebase forbids.

## 2. Response format (SRS §5)

Both success and error responses follow the §5 envelope, with matching `meta`.

**Success** (any 2xx JSON under `/api`):

```json
{ "success": true,
  "data": { "...": "the resource or list" },
  "meta": { "request_id": "6f1c…", "timestamp": "2026-07-10T04:31:00+00:00" } }
```

**Error**:

```json
{ "success": false,
  "error": { "code": "ACCOUNT_LOCKED", "message": "Authentication failed." },
  "request_id": "6f1c…",
  "meta": { "request_id": "6f1c…", "timestamp": "2026-07-10T04:31:00+00:00" } }
```

How it works, without disturbing the rest of the stack:

- **Success** wrapping is done once, at the edge, by `ResponseEnvelopeMiddleware`
  (`app/core/middleware.py`) — only 2xx `application/json` responses under `/api`, never
  double-wrapping, leaving `/health`, `/openapi.json` and file/CSV exports untouched.
  Controlled by `RESPONSE_ENVELOPE_ENABLED` (on by default). The backend **test suite**
  runs with it off so unit/API tests assert the inner resource contract directly; the
  envelope itself is verified in `tests/test_response_envelope.py`.
- **Errors** are rendered centrally by `app/identity/errors.py` for every `IdentityError`.
  `request_id` is also kept at the top level for backward compatibility.
- The **frontend** unwraps the envelope in one place (`services/envelope.ts`, used by the
  axios response interceptor and the bare refresh client), so every service consumes the
  inner payload and is oblivious to the wrapping.

Both envelopes carry the same correlation id, which is also on the `X-Request-ID`
response header (§4 below).

## 3. Error codes & status (SRS §14)

Machine-readable `error.code` values and their HTTP status live in `ErrorCode` /
`_STATUS` in `app/identity/errors.py`. Highlights beyond the standard 4xx: `423 Locked`
(account locked), `410 Gone` (a link that _was_ valid — expired/used invitation, reset,
or verification token), `429` (rate limited / too many attempts, always with
`Retry-After`). Authentication failures are uniform and never reveal _why_ (no
enumeration, no lock-reason leak).

## 4. Request correlation (SRS §15)

`RequestContextMiddleware` (`app/core/middleware.py`) gives every request a stable id:
the inbound `X-Request-ID` if the caller sent one (trimmed, length-capped), else a fresh
UUID4. It is stored on `request.state.request_id`, flows into the error envelope's
`request_id`, and is echoed on the `X-Request-ID` response header so a caller can quote
it in a bug report. Configure the header name with `REQUEST_ID_HEADER`.

## 5. Security headers (SRS §16, §23)

`SecurityHeadersMiddleware` applies, to every response including errors:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` (`SECURITY_REFERRER_POLICY`) |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` (`SECURITY_CSP`) |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `Strict-Transport-Security` | opt-in over TLS via `SECURITY_HSTS_ENABLED` |

Deny-by-default CSP is safe because this surface serves JSON, not HTML; the SPA is served
separately. Set `SECURITY_HEADERS_ENABLED=false` only if a reverse proxy already injects
these. Covered by `backend/tests/test_http_hardening.py`.
