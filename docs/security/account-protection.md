# Account Protection & Risk-Based Authentication (Phase 4 Part 4.2.2.3.4)

> Authentication is no longer binary. A correct password from a trusted device with
> normal behaviour is allowed; a correct password from a suspicious context is
> challenged; repeated failures lock; a known attack pattern is blocked. The platform
> now evaluates *risk*, not just *credentials*.

## Where it hooks into login (§6, §21)

[`AccountProtectionService`](../../backend/app/identity/protection/service.py) wraps the
existing password check with three hooks in
[`authentication_service.login`](../../backend/app/identity/auth/authentication_service.py):

```
login attempt
  → pre_check            (blocked IP? active lock? security review?)   ← before password
  → verify password
      fail → record_failure  (count, detect brute-force, lock at threshold)
  → evaluate_login_attempt   (score risk, run rules → ALLOW/CHALLENGE/MFA/BLOCK/REVIEW)
  → issue tokens (only on ALLOW)
```

Every branch returns a **generic** response — an attacker never learns from the
response whether the account exists or exactly why they were refused (§33). The
failing attempts stay `INVALID_CREDENTIALS`; only a *locked* account returns 423, and
that is the same contract as Part 4.2.2.1.

## Why we extended `login_history` instead of a new `login_attempts` table

The SRS §17 sketches a `login_attempts` table, but `login_history` (Part 4.2.2.1)
already records every attempt with IP, user agent and country. This part **adds** the
risk columns (`organization_id`, `device_fingerprint`, `risk_score`, `decision`) to it
rather than forking a parallel writer. The genuinely-new tables are `account_locks`,
`identity_risk_events`, `blocked_ips` and `identity_protection_rules`.

## The services (§18, §19)

| Service | Responsibility |
| ------- | -------------- |
| `AccountProtectionService` | Coordinates the login-time workflow |
| `AccountLockoutService` | Progressive, stateful locks ([account-lockout.md](./account-lockout.md)) |
| `BruteForceDetectionService` | Attack patterns from attempt history ([brute-force-protection.md](./brute-force-protection.md)) |
| `RiskScoringService` + `LoginAnomalyService` | Signals → 0–100 score ([risk-based-authentication.md](./risk-based-authentication.md)) |
| `IdentityProtectionRuleService` | Admin `conditions → decision` rules ([identity-protection-rules.md](./identity-protection-rules.md)) |
| `BlockedIpService` | Deny an IP at the door |
| `AdaptiveRateLimitService` | Tighten limits as risk rises (§10) |
| `CaptchaService` | Provider-agnostic seam (§28), disabled by default |
| `SecurityAlertService` | Best-effort user/admin alerts (§30) |

## Account status model (§5)

`IdentityStatus` gains `LOCKED`, `PASSWORD_RESET_REQUIRED`, `MFA_REQUIRED` and
`SECURITY_REVIEW_REQUIRED`. Transient lockout lives in `account_locks` (it has an
expiry and escalates); a 5th consecutive lock parks the account in the durable
`SECURITY_REVIEW_REQUIRED` state that only an administrator lifts.

## Admin console (§20, §22–§27)

Under **Settings → Security → Account protection**, gated by `security.protection`:
a dashboard of widgets, login attempts, risk events, account locks (with an audited
unlock), blocked IPs, and the protection-rules editor. Endpoints live under
`/api/v1/security/*`.

## Security posture (§33)

- Generic login errors — no enumeration, no risk-signal leak in the response.
- Every attempt is stored; every lock/unlock/block/rule change is audited.
- Admin unlock requires a reason and the `security.protection` permission.
- Risk events are an append-only stream; normal admins cannot delete them.

## Audit (§31)

`ACCOUNT_LOCKED` · `ACCOUNT_UNLOCKED` · `BRUTE_FORCE_DETECTED` ·
`CREDENTIAL_STUFFING_DETECTED` · `RISK_LOGIN_DETECTED` · `LOGIN_CHALLENGE_REQUIRED` ·
`IP_BLOCKED` · `IP_UNBLOCKED` · `PROTECTION_RULE_CREATED/UPDATED/DELETED/TRIGGERED` ·
`CAPTCHA_REQUIRED` · `SECURITY_REVIEW_REQUIRED`. A reachability test greps the sources
for every one, so none can become dead code.

## Related

- [Risk-based authentication](./risk-based-authentication.md)
- [Brute-force protection](./brute-force-protection.md)
- [Account lockout](./account-lockout.md)
- [Identity protection rules](./identity-protection-rules.md)
