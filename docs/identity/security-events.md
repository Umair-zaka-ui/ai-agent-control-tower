# Security Events (Phase 4 Part 4.2.1)

Every authentication action records a security event
(`SecurityEventService.record` → `security_events`, SRS §13). Auth events are
their own stream and are *not* doubled into the business audit log.

## Event types (`AuthEventType`)

| Event | When |
| ----- | ---- |
| `AUTH_LOGIN_SUCCESS` | password login succeeds |
| `AUTH_LOGIN_FAILED` | bad credentials or inactive identity |
| `AUTH_LOGIN_LOCKED` | account locked after too many failures (SRS 4.2.2.1 §10) |
| `AUTH_LOGOUT` | user logs out |
| `TOKEN_REFRESHED` | refresh token rotated, new access issued |
| `REFRESH_TOKEN_REUSED` | already-rotated refresh token replayed (theft signal) |
| `SESSION_CREATED` | a login created a session (Part 4.2.2.2 §26) |
| `SESSION_UPDATED` | session state changed |
| `SESSION_REVOKED` | logout, admin revocation, device block, account disabled |
| `SESSION_TIMEOUT` | idle or absolute deadline reached |
| `SESSION_SUSPICIOUS` | a security signal flagged the session |
| `SESSION_LIMIT_EXCEEDED` | oldest session evicted past `SESSION_MAX_CONCURRENT` |
| `DEVICE_REGISTERED` | first login from a device |
| `DEVICE_TRUSTED` | user marked a device trusted |
| `DEVICE_BLOCKED` | device blocked, or a blocked device attempted login |
| `TOKEN_ROTATED` | refresh token rotated to a successor |
| `TOKEN_REUSE_DETECTED` | forensic anchor on the replayed token |
| `TOKEN_REVOKED` | an access/refresh token was revoked |
| `API_KEY_USED` | an agent/service key authenticated (Part 4.2.2) |
| `API_KEY_REVOKED` | a key was revoked |
| `SERVICE_ACCOUNT_AUTHENTICATED` | a service account authenticated |
| `EXTERNAL_CLIENT_AUTHENTICATED` | an external client authenticated |
| `SUSPICIOUS_LOGIN` | anomaly heuristics (future) |
| `SESSION_EXPIRED` | a session passed its expiry |
| `SESSION_REVOKED` | a session was revoked |
| `MFA_CHALLENGE_ISSUED` | login required a second factor; challenge issued (§24) |
| `MFA_SUCCEEDED` | second factor verified, session elevated to AAL2 |
| `MFA_FAILED` | second-factor verification failed |
| `MFA_ENROLLED` | an identity enrolled a second factor (Part 4.2.x) |
| `MFA_DISABLED` | a second factor was removed (Part 4.2.x) |

## Event fields (`security_events`)

`id` · `organization_id` · `event_type` · `actor_type` (identity type) ·
`actor_id` (identity id) · `target_type` · `target_id` · `request_id` ·
`correlation_id` · `ip_address` · `meta` (includes `auth_method`, user agent) ·
`created_at`.

## Auth methods (`AuthMethod`, SRS §10)

`PASSWORD` · `JWT` · `REFRESH_TOKEN` · `API_KEY` · `OAUTH2` · `OIDC` · `SAML` ·
`CLIENT_CREDENTIALS` · `SYSTEM_INTERNAL`. The method is stored on every security
event (`meta.auth_method`) so audits can tell *how* a request authenticated.

## Request security metadata (SRS §14)

Captured per event: IP address, user agent, request id, correlation id. Device
fingerprint and GeoIP (country/city) are placeholders for a later part.


## Reading the stream (DoD §32 "…and audit user sessions")

`security_events` was write-only until Part 4.2.2.2: 5k+ rows, no `SELECT` anywhere in
`app/`, and deliberately not mirrored into `audit_logs`. **An audit event that nobody
can read is not an audit trail.**

| Endpoint | Scope | Permission |
| -------- | ----- | ---------- |
| `GET /api/v1/identity/security-events` | the caller's organization | `session.view` |
| `GET /api/v1/identity/security-events/types` | filter values this org has produced | `session.view` |
| `GET /api/v1/identity/sessions/{id}/events` | one session, oldest first | `session.view` |
| `GET /api/v1/auth/security-events` | **the caller's own events only** | authenticated |

Filters: `event_type`, `actor_id`, `session_id`, `since`, `until`, `limit`, `offset`.
Responses carry `total` after filtering, so a client can page without guessing.

### Two authorization decisions worth stating

1. The org-wide stream is gated on **`session.view`, not `audit.view`.** Every built-in
   role — including `VIEWER` — holds `audit.view`, and this stream carries other people's
   IP addresses, devices and login history. A test caught this before it shipped.
2. `/api/v1/auth/security-events` **accepts no `actor_id` parameter.** A user is entitled
   to see events recorded against their own identity — that is how they notice an
   intrusion — and entitled to see nobody else's. Making the scope a parameter would make
   the boundary a validation problem instead of a structural one.

### Performance

Migration `0011` indexes the read path. Verified with `EXPLAIN (ANALYZE)`:

| Query | Index | Time |
| ----- | ----- | ---- |
| org timeline | `ix_security_events_org_created` | 0.13 ms |
| one session's history | `ix_security_events_session_id` (expression) | 0.06 ms |
| actor timeline | `ix_security_events_actor_created` | 0.06 ms |

The session-history filter uses `meta ->> 'session_id'` — the text extraction, not a
containment operator — because only that form can use the expression index.
