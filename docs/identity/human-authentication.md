# Human Authentication Guide (Phase 4 Part 4.2.2.1)

Status: **implemented**. Email/password login, JWT access tokens, rotating
refresh tokens, session management, account lockout, argon2id hashing and the
password policy are live under `/api/v1/auth`. This builds on the 4.2.1 service
layer (AuthenticationService, TokenService, RefreshTokenService, SessionService,
SecurityEventService) — those were not rebuilt.

## Endpoints (SRS §16)

| Method + Path | Purpose | Auth |
| ------------- | ------- | ---- |
| `POST /api/v1/auth/login` | email + password → access + refresh token (or MFA challenge) | public |
| `POST /api/v1/auth/mfa/verify` | challenge + second factor → tokens (seam; verifier lands later) | challenge token |
| `POST /api/v1/auth/refresh` | rotate refresh token → new access token | refresh token |
| `POST /api/v1/auth/logout` | revoke current session + refresh-token family | access token |
| `GET /api/v1/auth/me` | current identity, roles, permissions, assurance | access token |
| `GET /api/v1/auth/sessions` | caller's active sessions | access token |
| `DELETE /api/v1/auth/sessions/{id}` | revoke one of the caller's sessions | access token |

The legacy `/auth/login` (1-day token) is untouched and continues to work; the
frontend now uses the `/api/v1/auth/*` endpoints.

## Login sequence (SRS §5, §6)

```mermaid
sequenceDiagram
    participant U as Browser
    participant A as /api/v1/auth/login
    participant S as AuthenticationService
    participant H as LoginHistoryService
    participant DB as PostgreSQL

    U->>A: { email, password }
    A->>S: login(email, password, ip, ua)
    S->>H: is_locked(email)?  (SRS §10)
    alt locked
        H-->>S: locked
        S->>DB: record AUTH_LOGIN_LOCKED + login_history
        S-->>A: ACCOUNT_LOCKED (423)
    else not locked
        S->>DB: authenticate_user (argon2id verify, §11)
        alt bad credentials
            S->>DB: login_history(success=false) + AUTH_LOGIN_FAILED
            S-->>A: INVALID_CREDENTIALS (401, generic)
        else ok
            S->>S: assert status ACTIVE (§6); rehash bcrypt→argon2id if needed
            S->>DB: create session + issue refresh token
            S->>DB: login_history(success=true) + AUTH_LOGIN_SUCCESS
            S-->>A: { access_token, refresh_token, expires_in, user }
        end
    end
    A-->>U: 200 / 401 / 423
```

## Tokens (SRS §6)

- **Access token** — argon2-independent JWT, 15-minute lifetime
  (`AUTH_ACCESS_TOKEN_TTL_SECONDS`), carries the full identity claim set incl.
  `assurance_level` / `amr`.
- **Refresh token** — opaque `rt_…`, 7-day lifetime, stored **hashed only**,
  **rotated on every use**; replaying a rotated token is detected as theft and
  revokes the whole token family *and the session* (`REFRESH_TOKEN_REUSED`).

## Password hashing (SRS §11)

`argon2id` is the primary scheme (`app/core/security.py`). Pre-4.2.2.1 bcrypt
hashes still verify and are **transparently re-hashed to argon2id on the next
successful login** (`needs_rehash`). No secret is ever stored or logged in
plaintext.

## Password policy (SRS §9)

The policy — ≥ 12 chars, upper + lower + digit + special, a common-password
blocklist (normalised so `Password123!` is caught), and no email/username
substring — is defined **once** in `app/identity/security/passwords.py`.
`PasswordService` (auth layer) is a thin facade over it; the policy lives in the
lower module because `credential_service` and `tokens/service` import it at
module scope, so defining it in the auth package would create an import cycle.

Every path that sets a human password goes through `hash_user_password`, which
validates before hashing:

| Path | Call site |
| ---- | --------- |
| `POST /auth/register` | `services/auth_service.py:register_organization` |
| `POST /users` | `api/routes/users.py:create_user` |
| `IdentityService.create_user` | `identity/services/identity_service.py` |

A `PasswordPolicyError` is mapped to HTTP **422** by a global handler
(`identity/errors.py`), so a weak password is never a 500. Pydantic's
`min_length=12` rejects short passwords early, but is *not* the policy — long-
but-weak passwords (`alllowercase123!`) are caught by the complexity check.

The login path only verifies; the re-hash on login (`needs_rehash`) deliberately
skips validation so a legacy user whose password predates this policy can still
log in.

## Account lockout (SRS §10)

`AUTH_LOCKOUT_THRESHOLD` (5) failed attempts within
`AUTH_LOCKOUT_WINDOW_SECONDS` (15 min) lock the account for the remainder of the
window. Computed from `login_history`, so it survives restarts. Crossing the
threshold emits `AUTH_LOGIN_LOCKED`; subsequent attempts return `ACCOUNT_LOCKED`
(HTTP 423) before credentials are even checked.

## Refresh & logout (SRS §7, §8)

- **Refresh:** validate → rotate (revoke old, issue new) → new access token.
- **Logout:** revoke the session and its refresh-token family; the access token
  expires naturally within 15 minutes.

## Frontend flow (SRS §18–20)

- `AuthContext` stores the access token (memory + localStorage), the refresh
  token and the access-token expiry.
- **Silent refresh** (`SILENT_REFRESH_LEAD_MS`, 5 min before expiry) rotates the
  token in the background so the user never notices (SRS §20).
- **Reactive refresh**: the axios interceptor catches a `401`, performs a
  single coalesced refresh and replays the request; if the refresh fails it
  broadcasts `act:session-expired`.
- `SessionExpiredModal` then prompts re-authentication.

## Error codes (SRS §21)

`INVALID_CREDENTIALS` · `ACCOUNT_LOCKED` · `ACCOUNT_DISABLED` ·
`PASSWORD_EXPIRED` · `TOKEN_EXPIRED` · `TOKEN_INVALID` · `SESSION_REVOKED` ·
`REFRESH_TOKEN_REUSED` / `REFRESH_FAILED`.

## Security events (SRS §22)

`AUTH_LOGIN_SUCCESS` · `AUTH_LOGIN_FAILED` · `AUTH_LOGIN_LOCKED` · `AUTH_LOGOUT`
· `TOKEN_REFRESHED` · `TOKEN_REVOKED` · `SESSION_REVOKED`.

## Data model (SRS §12, §13)

- Sessions / refresh tokens: existing `sessions` / `refresh_tokens` tables (0006).
- `login_history` (migration `0008_auth_login_history`): one row per attempt —
  `user_id?`, `email`, `success`, `failure_reason`, `ip_address`, `user_agent`,
  `country?`, `city?`, `created_at`.

## Tests (SRS §25)

`tests/identity/auth/test_human_auth_endpoints.py` covers success, wrong
password, unknown email, suspended user, lockout, refresh rotation + reuse,
logout, `/me`, session list/revoke and the password policy.
