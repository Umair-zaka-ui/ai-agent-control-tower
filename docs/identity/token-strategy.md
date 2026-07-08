# Token Strategy (Phase 4 Part 4.2.1)

Two token categories (SRS §6).

## Access token

- **Purpose:** authorize short-lived API requests.
- **Lifetime:** 15 minutes (`settings.AUTH_ACCESS_TOKEN_TTL_SECONDS`).
- **Signing:** JWT (HS256) with the platform secret.
- **Validation:** signature + `exp` + `iss` + `aud` + `token_type == access`
  (+ revocation once the table lands).

Claims (`TokenService.create_access_token`, SRS §7):

```json
{
  "sub": "user_123", "identity_id": "user_123", "identity_type": "HUMAN_USER",
  "organization_id": "org_456", "roles": ["ROLE_ADMIN"],
  "permissions": ["agent.view", "policy.create", "approval.review"],
  "scopes": [], "session_id": "sess_789", "auth_method": "PASSWORD",
  "assurance_level": "AAL1", "amr": ["pwd"], "mfa_pending": false,
  "token_type": "access", "iss": "ai-agent-control-tower",
  "aud": "ai-agent-control-tower-api", "iat": 1710000000, "exp": 1710000900,
  "jti": "tok_abc"
}
```

Machine tokens carry `scopes` and `credential_id` instead of user roles.
`assurance_level` / `amr` / `mfa_pending` carry the authentication assurance
(SRS §24) so authorization can require step-up MFA; old tokens without these
claims default to `AAL1` / `[]` / `false` on resolution.

## MFA challenge token

When login requires a second factor, a distinct short-lived access token is
issued at assurance `AAL0` with `mfa_pending: true` (TTL
`AUTH_MFA_CHALLENGE_TTL_SECONDS`, default 5 min). It proves only the primary
factor: `require_scope` / `require_assurance` reject it, and it is exchanged at
the MFA-verify step for a full `AAL2` token + refresh token. See
[authentication-architecture.md](authentication-architecture.md) (MFA & step-up).

## Refresh token

- **Purpose:** obtain a new access token without re-login.
- **Lifetime:** 7–30 days (`settings.AUTH_REFRESH_TOKEN_TTL_SECONDS`, default 7d).
- **Storage:** database, **hashed only** (`refresh_tokens.token_hash`); the
  plaintext (`rt_…`) is returned once.
- **Rotation:** every use issues a new token and revokes the old
  (`revoked_at` + `rotated_to_id`).
- **Reuse detection:** presenting an already-rotated token is treated as theft →
  the token family **and the session itself** are revoked, and re-login is
  required (`RefreshTokenService.is_reuse` + `revoke_session_family` +
  `SessionService.revoke`).
- **Revocation is immediate (Part 4.2.2.2).** `authenticate` loads the caller's
  `auth_sessions` row on every authenticated request, so logout, admin
  force-logout, device block, idle timeout, absolute timeout and token-reuse
  termination all take effect on the very next request. See
  [session-lifecycle.md](./session-lifecycle.md) and
  [ADR-0007](../architecture/adr/0007-stateful-session-validation.md).
- **The legacy `/auth/login` surface is the exception.** Its 24-hour JWT carries no
  `session_id`, so there is no session to check. It is now the platform's only
  non-revocable credential.

Planned columns (Part 4.2.2, see [migration-plan.md](migration-plan.md)):
`family_id`, `rotated_from_id`, `reuse_detected_at` for first-class token
families independent of the session.

## Credential storage rules (SRS §11)

| Credential | Storage |
| ---------- | ------- |
| Passwords | **argon2id** (Part 4.2.2.1); legacy bcrypt hashes verify and auto-upgrade on next login |
| API keys | hash only + display prefix + `last_used_at` + `expires_at` + `status` |
| Refresh tokens | hash only + family + rotation chain + `revoked_at` + `expires_at` |
| Client secrets | hash only |

**No secret is ever stored or logged in plaintext.**
