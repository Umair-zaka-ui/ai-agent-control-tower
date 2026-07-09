# Account Recovery (Phase 4 Part 4.2.2.3.3)

> Users forget passwords, employees leave, email addresses change, and accounts get
> compromised. This is the map of how the platform recovers an account securely,
> auditably, and without leaking who exists.

## Components (§3, §19)

| Service | Responsibility |
| ------- | -------------- |
| `RecoveryService` | Coordinates the workflow; one entry point per route |
| `PasswordResetService` | Forgot-password token issue + reset ([password-reset.md](./password-reset.md)) |
| `EmailChangeService` | Verified email change ([email-verification.md](./email-verification.md)) |
| `RecoveryAuditService` | Records every recovery event to `security_events` |
| `EmailService` | Renders + sends the recovery emails (§16) |

Email *verification* itself (activation) was built in Part 4.2.2.3.1 and is unchanged;
this part adds reset, verified email **change**, and the recovery dashboard.

## Why not the tables the SRS sketches

§5 lists `password_reset_requests`, `email_verification_requests` and `recovery_events`.
We built one new table and reused two existing ones — deliberately:

| SRS table | What we did | Why |
| --------- | ----------- | --- |
| `password_reset_requests` | **Created** | Genuinely new state |
| `email_verification_requests` | Reused `email_verifications` + `purpose`/`new_email` columns | One table already models "a hashed token proving control of an address"; a change is that with a target |
| `recovery_events` | Reused `security_events` | The audit UI, export and `recovery-events` endpoint already read that stream; a parallel table is plumbing rebuilt for no gain |

Same rationale, and the same one-source-of-truth discipline, as the prior parts.

## The whole picture

```
Forgot password ──▶ POST /forgot-password ──▶ (uniform ack)
                                              │ if account real + has password
                                              ▼
                         rst_ token (30m, hashed) ──▶ email
                                              │
User clicks link ──▶ /reset-password/:token ──▶ POST /reset-password
                                              ▼
         policy + no-reuse + argon2id + history ──▶ revoke ALL sessions ──▶ alert email

Change email ──▶ POST /change-email (re-auth) ──▶ vrf_ token to NEW address (24h)
                                              ▼
Confirm ──▶ /verify-new-email/:token ──▶ swap primary email ──▶ alert OLD address
```

## Security properties (§14, §26)

- **HTTPS-only, no token logging** — `notification_service` logs subject + recipients,
  never the body where the link lives.
- **No enumeration** — forgot-password is byte-identical for known and unknown
  addresses; email-change conflicts are only visible to the authenticated owner.
- **Every recovery token is hashed** (SHA-256) and single-use.
- **Sessions invalidated after reset** (§13) — all of them.
- **Alerts to the mailbox an attacker does not control** — a completed reset alerts the
  account address; a completed email change alerts the *old* address (§17).
- **Automatic cleanup** of expired requests, bounded (§26).

## Dashboard (§18)

`GET /api/v1/security/recovery-events` (`recovery.view`) — reset requests/completions/
failures, email changes, expiries — for a security administrator. Surfaced in the UI at
**Settings → Security → Recovery events**.

## Audit (§24)

`PASSWORD_RESET_REQUESTED` · `PASSWORD_RESET_COMPLETED` · `PASSWORD_RESET_FAILED` ·
`EMAIL_CHANGE_REQUESTED` · `EMAIL_CHANGED` · `EMAIL_CHANGE_VERIFIED` ·
`RECOVERY_REQUEST_EXPIRED` · `RECOVERY_REQUEST_REVOKED`.

## Related

- [Password reset](./password-reset.md)
- [Email verification & change](./email-verification.md)
- [Credential management](./credential-management.md)
