# Authentication — Database Migration Plan (Phase 4 Part 4.2.x)

Part 4.2.1 defines the **model direction** (SRS §12). No schema change ships in
4.2.1 — the auth architecture runs on the tables delivered in Part 4.1
(`sessions`, `refresh_tokens`, `device_sessions`, `security_events`) plus the
identity `status` lifecycle. This plan sequences the remaining tables.

## Already present (Part 4.1, migrations 0006 / 0007)

| Table | Used by |
| ----- | ------- |
| `sessions` | `SessionService` |
| `refresh_tokens` | `RefreshTokenService` (issue/rotate/reuse) |
| `device_sessions` | device binding (placeholder) |
| `security_events` | `SecurityEventService` |
| `users.status` / `organizations.status` | identity status checks |

## Shipped — Part 4.2.2.1 (`0008_auth_login_history`)

| Table | Used by |
| ----- | ------- |
| `login_history` | `LoginHistoryService` — per-attempt audit + the account-lockout window (SRS §10, §13). Supersedes the placeholder `login_attempts`. |

Password hashing moved to **argon2id** in this part (no schema change — the
existing `users.password_hash` column stores the new hash; legacy bcrypt hashes
verify and auto-upgrade on next login).

## Planned — Part 4.2.2 (`0008_auth_credentials`)

| Table | Purpose |
| ----- | ------- |
| `identity_credentials` | unified credential records (password/api-key/secret) with `hash`, `prefix`, `status`, `last_used_at`, `expires_at` |
| `api_keys` | agent/service API keys (hash + prefix + lifecycle) |
| `service_account_credentials` | service-account secrets |
| `external_client_credentials` | external-client secrets |
| `token_revocations` | explicit access/refresh `jti` revocation list |
| `login_attempts` | brute-force / credential-stuffing tracking |

Column additions to `refresh_tokens`: `family_id`, `rotated_from_id`,
`reuse_detected_at` (first-class token families independent of the session).
Column additions to `sessions`: `refresh_token_family_id`, `device_name`,
`status` (ACTIVE/EXPIRED/REVOKED/SUSPICIOUS), `assurance_level`
(AAL1/AAL2 — so a rotated token preserves the session's MFA assurance).

## Planned — MFA / step-up (`0010_auth_mfa`, SRS §24)

The assurance seam (`assurance_level`, `amr`, `mfa_pending`, challenge tokens,
`require_assurance`) ships in 4.2.1 as code + claims. These tables activate it:

| Table | Purpose |
| ----- | ------- |
| `mfa_enrollments` | per-identity factors (`method`, hashed TOTP secret / WebAuthn credential, `status`, `confirmed_at`) — drives `_mfa_required` / `_verify_second_factor` |
| `mfa_recovery_codes` | single-use recovery codes, hash only |
| `mfa_policies` | org-level policy: require MFA (all / role-scoped), grace period |

## Planned — Part 4.2.3 (`0009_auth_endpoints` + SSO)

- `/api/v1/auth/*` endpoints (login/refresh/logout/me/sessions) migrate the
  legacy `/auth/login` onto `AuthenticationService`.
- OAuth2 / OIDC provider config tables (`oidc_providers`, `oauth_identities`).
- SAML remains architecture-only (SRS §5) — no table blocks it.

## Principles

- Every migration is **additive and nullable-default** so existing rows and the
  running platform are never broken (as with 0006 / 0007).
- No secret column ever stores plaintext (SRS §11).
