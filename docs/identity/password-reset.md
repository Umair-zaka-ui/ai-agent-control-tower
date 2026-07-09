# Password Reset (Phase 4 Part 4.2.2.3.3)

> Recovery is the highest-risk part of an identity platform, so it must never become
> the weakest link. Forgot-password reuses the same discipline as the rest of the
> stack: opaque hashed single-use tokens, the credential write path, rate limiting,
> and a uniform response that reveals nothing.

## The token (§6, §7, §8)

```
rst_<43 url-safe chars>          32 bytes (256 bits) of secrets.token_urlsafe
     ↓ sha256
password_reset_requests.token_hash    the only thing persisted
```

256-bit CSPRNG, URL-safe, single use, **30 minutes**. Never a sequential/DB/user id.
The plaintext exists only in the email and the link the user clicks; a database dump
cannot reset anyone's password.

## Forgot-password is not an existence oracle (§9)

`POST /api/v1/auth/forgot-password` **always** answers:

```json
{ "success": true, "message": "If an account exists, recovery instructions have been sent." }
```

The response and its timing do not depend on whether the address is known — the
`ForgotPasswordPage` shows the same confirmation even on a network error, so a failure
cannot be used to probe for accounts either. A token is minted and mailed only when the
address maps to a real account **with a real password** (an SSO/SCIM identity has
nothing to reset).

A new request **supersedes** any outstanding one (`RECOVERY_REQUEST_REVOKED`): a fresh
link must invalidate the old, or "single use" becomes "N concurrent valid links".

## Reset applies the full credential discipline (§10, §13)

```
POST /reset-password {token, new_password}
  → validate token (invalid / expired / used / superseded)
  → complexity + no-reuse + argon2id + history + lifecycle stamp   (shared write path)
  → revoke EVERY session and refresh token                          (§13)
  → mark token USED, supersede siblings
  → email a "password changed" alert                                (§17)
```

The reset delegates the credential write to
[`CredentialService.apply_recovery_reset`](../../backend/app/identity/credentials/service.py),
so a reset is subject to exactly the same policy, history and hashing as a voluntary
change — recovery is not a bypass. Because a reset exists for the compromised-account
case, **every** session is revoked; no live session may survive it.

## Dead links say which kind of dead (§14)

| Situation | Code | HTTP |
| --------- | ---- | ---- |
| No such token | `RESET_TOKEN_INVALID` | 400 |
| Past `expires_at` | `RESET_TOKEN_EXPIRED` | **410 Gone** |
| Already used | `RESET_TOKEN_USED` | **410 Gone** |
| Superseded by a newer request | `RESET_TOKEN_INVALID` | 400 |

410, not 404: the link *was* valid. A weak/reused new password returns 422 and leaves
the token usable, so the user can retry on the same valid link.

## Brute force & cleanup (§15, §26)

`forgot-password`, `reset-password` and `verify-new-email` are rate limited (5/min/IP,
Postgres-backed). PENDING requests past their 30 minutes are materialised to `EXPIRED`
on read and by a bounded reaper (`RecoveryService.expire_stale`), emitting
`RECOVERY_REQUEST_EXPIRED`.

## Audit (§24)

`PASSWORD_RESET_REQUESTED` · `PASSWORD_RESET_COMPLETED` · `PASSWORD_RESET_FAILED` ·
`RECOVERY_REQUEST_EXPIRED` · `RECOVERY_REQUEST_REVOKED` — in `security_events`, readable
via `GET /api/v1/security/recovery-events` (`recovery.view`). A reachability test greps
for every one, so none can become dead code.

## Related

- [Recovery overview](./recovery.md)
- [Email verification & change](./email-verification.md)
- [Credential management](./credential-management.md)
