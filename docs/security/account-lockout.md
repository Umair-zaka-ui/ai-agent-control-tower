# Account Lockout (Phase 4 Part 4.2.2.3.4 §8, §29)

> The lock is a row, not a recomputed window. Each successive lock is longer, and a
> repeatedly-attacked account ends up in a human's hands.

## Progressive durations (§8)

[`AccountLockoutService`](../../backend/app/identity/protection/lockout.py) creates an
`account_locks` row whose duration is chosen from how many times the account has
already been locked:

| Lock # | Duration |
| ------ | -------- |
| 1st | 15 minutes |
| 2nd | 30 minutes |
| 3rd | 1 hour |
| 4th | 24 hours |
| 5th | **indefinite** → `SECURITY_REVIEW_REQUIRED` |

The durations are `PROTECTION_LOCKOUT_DURATIONS` in settings. The 5th lock escalates:
the row is `ESCALATED`, the user's status becomes `SECURITY_REVIEW_REQUIRED` and
`is_active` is cleared, so only an administrator can restore access.

## The lock is the source of truth

`active_lock(user_id)` returns the current lock, **materialising expiry on read** — an
`ACTIVE` lock past its `expires_at` is flipped to `EXPIRED` and treated as gone. So the
admin list and the login path can never disagree about whether an account is locked
(the same discipline as invitation/reset expiry).

## How a lock engages at login

A failed password does **not** immediately return "locked". The failing attempt is a
generic `INVALID_CREDENTIALS`; `record_failure` counts it and, at the threshold, creates
the lock. The lock bites on the *next* attempt, which `pre_check` refuses with `423
ACCOUNT_LOCKED` (with a `Retry-After` header when the lock is time-bounded). This
preserves the exact contract from Part 4.2.2.1 while adding progression and escalation.

Both `ACCOUNT_LOCKED` (new) and `AUTH_LOGIN_LOCKED` (legacy, still keyed on by earlier
dashboards/tests) are recorded.

## Administrative unlock (§29)

Settings → Security → Account locks → **Unlock**. The workflow requires a **reason**,
which is stored on the lock and in an `ACCOUNT_UNLOCKED` audit event; a security-review
lock also reactivates the account (`SECURITY_REVIEW_REQUIRED` → `ACTIVE`). The user is
notified by a best-effort email. Unlocking needs the `security.protection` permission
and is org-scoped — an admin can only unlock within their own organization.

## Notifications (§30)

The locked user is emailed when their account is locked (with how long) and when it is
unlocked. Mail is best-effort and suppressed in dev/test, exactly like every other email.

## Related

- [Account protection overview](./account-protection.md)
- [Brute-force protection](./brute-force-protection.md)
