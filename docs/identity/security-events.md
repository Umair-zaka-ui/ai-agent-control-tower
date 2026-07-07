# Security Events (Phase 4 Part 4.2.1)

Every authentication action records a security event
(`SecurityEventService.record` → `security_events`, SRS §13). Auth events are
their own stream and are *not* doubled into the business audit log.

## Event types (`AuthEventType`)

| Event | When |
| ----- | ---- |
| `AUTH_LOGIN_SUCCESS` | password login succeeds |
| `AUTH_LOGIN_FAILED` | bad credentials or inactive identity |
| `AUTH_LOGOUT` | user logs out |
| `TOKEN_REFRESHED` | refresh token rotated, new access issued |
| `REFRESH_TOKEN_REUSED` | already-rotated refresh token replayed (theft signal) |
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
