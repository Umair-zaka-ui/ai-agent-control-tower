# Credential Management (Phase 4 Part 4.2.2.3.2)

> Passwords are created, changed, expired, reset and audited through one write path,
> so the full discipline is applied exactly once.

## Why not five new tables

The SRS sketches `credentials`, `password_policy`, `temporary_credentials` and
`credential_events` tables. We deliberately did **not** create them, because each would
fork an existing source of truth and put the whole auth stack at risk for no functional
gain:

| SRS table | What we did instead | Why |
| --------- | ------------------- | --- |
| `credentials` | The live credential stays `users.password_hash` | A second store for the *active* credential would have to be kept in lock-step with the column every login already reads |
| `password_policy` | Code-level single source (ADR-0004) + settings | The policy is logic, not rows; see [password-policy.md](./password-policy.md) |
| `temporary_credentials` | `users.must_change_password` + a short `password_expires_at` | A temporary password *is* the password — flagged, and forced to change at first login |
| `credential_events` | The existing `security_events` stream | The audit UI and export already read it; a parallel table would need all that plumbing rebuilt |

`password_history` **is** a real new table — see [password-history.md](./password-history.md).
The lifecycle fields (`password_changed_at`, `password_expires_at`, `must_change_password`)
are additive columns on `users`; NULL expiry means "never expires", the safe posture for
rows that predate the policy.

## The one write path

Every human-password write goes through
[`CredentialService`](../../backend/app/identity/credentials/service.py):

```
verify current  →  min-age gate  →  complexity  →  reuse check  →  argon2id hash
   →  old hash into history  →  stamp changed_at/expires_at/must_change  →  audit
   →  revoke other sessions (policy)
```

- **Verify current** — a wrong current password is `INVALID_CURRENT_PASSWORD` (401), and
  is itself audited as a `PASSWORD_POLICY_VIOLATION`.
- **Minimum age (§6)** — a password cannot be changed again within `PASSWORD_MIN_AGE_HOURS`
  (`PASSWORD_MIN_AGE`, 409), so a user cannot cycle through history back to a favourite.
  A forced/first-login change is exempt.
- **Reuse (§10)** — see [password history](./password-history.md).
- **Revoke other sessions (§15)** — changing your password signs out your *other*
  sessions by default; a reset signs out *all* of them. A stolen session must not outlive
  the credential it rode in on.

## Expiration (§11)

`password_expires_at = changed_at + PASSWORD_MAX_AGE_DAYS` (default 90; `0` disables).
Expiry does not block *login* — it blocks *access*: login still issues a session but
returns `password_change_required`, emits `PASSWORD_EXPIRED`, and the SPA routes the user
to the forced-change page. `GET /password-expiration` reports the caller's status and the
warning windows (14/7/3/1 days).

## Temporary passwords & first login (§12, §13)

An administrator with `credential.reset` calls `POST /admin/reset-password`. The service
issues a random policy-compliant temporary password, returned **exactly once** (the admin
never sees an existing password), sets `must_change_password` and a short
`TEMP_PASSWORD_TTL_HOURS` expiry, and revokes every session. At next login the user is
forced through the change flow (`FIRST_LOGIN_PASSWORD_CHANGED`) before any feature —
enforced by [`PasswordChangeGuard`](../../frontend/src/components/layout/PasswordChangeGuard.tsx),
which survives a page reload because the requirement is re-derived from the server.

## What an administrator can and cannot do (§16)

Can: reset a password, issue a temporary one, force a first-login change, and see the
org's credential posture (`GET /api/v1/security/password-dashboard`). Cannot: view or
export any existing password (only hashes exist), or act across organizations (a target
in another org returns 404, never "exists but not yours").

## Enforcement boundary (what "mandatory" means here)

A forced change (expired or temporary password) is enforced at the **session/UI
layer**, not hard-blocked at every backend endpoint:

- Login still issues a valid session and returns `password_change_required: true`.
- The SPA's [`PasswordChangeGuard`](../../frontend/src/components/layout/PasswordChangeGuard.tsx)
  then routes the user to the forced-change page before any feature, and the
  requirement is re-derived from the server on reload so it cannot be side-stepped
  by refreshing.

What this does **not** yet do: reject *other* API endpoints while a change is
outstanding. A raw API client holding the freshly-issued token could still call,
say, `GET /api/v1/auth/me` until it changes the password. For the acceptance
criterion ("first-login change is mandatory", via the mandatory UI flow) this is
met; for a hostile API client it is a gap.

**To close it** (a documented future seam): an `authenticate`-level dependency that
raises `FIRST_LOGIN_CHANGE_REQUIRED` / `PASSWORD_EXPIRED` (403) on every
non-credential route while `must_change_password` or expiry is outstanding — so the
requirement is enforced at the API, not only the SPA. The error codes already exist.

## Audit (§18)

`PASSWORD_CREATED` · `PASSWORD_CHANGED` · `PASSWORD_RESET` · `PASSWORD_EXPIRED` ·
`PASSWORD_ROTATED` · `PASSWORD_REUSED_ATTEMPT` · `TEMP_PASSWORD_CREATED` ·
`FIRST_LOGIN_PASSWORD_CHANGED` · `PASSWORD_POLICY_VIOLATION` — all in `security_events`
with the full forensic envelope. A reachability test greps the sources for every one, so
none can become dead code (a defect this codebase has produced before).

## Related

- [Password policy](./password-policy.md)
- [Password history](./password-history.md)
