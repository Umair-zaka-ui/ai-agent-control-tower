# Risk-Based Authentication (Phase 4 Part 4.2.2.3.4 §11–§15)

> Each login attempt receives a 0–100 risk score. The score, not the password alone,
> decides whether to allow, challenge, lock or block.

## Signals (§11, §12)

[`LoginAnomalyService`](../../backend/app/identity/protection/detection.py) collects the
observable facts of an attempt (IP, user agent, device fingerprint, country, failed-
attempt count) and derives anomaly flags:

`new_device` · `new_country` · `impossible_travel` · `suspicious_user_agent` ·
`failed_attempts_gt_3` · `failed_attempts_gt_5` · `blocked_ip` ·
`recent_password_reset` · `account_newly_created` · `old_inactive_account`.

**Baseline discipline.** "New device" and "new country" are only meaningful against a
history. On a user's first-ever successful login every device and country is new by
definition, so the relative flags are suppressed — otherwise every new account would
score as risky and operators would learn to ignore the signal. This mirrors
`SessionSecurityService.assess_login` from Part 4.2.2.2.

## Impossible travel (§13)

The initial model is deliberately simple: a **different country from the last
successful login within 2 hours** sets `impossible_travel`. Distance/time geodesics are
a documented future enhancement; GeoIP and proxy detection are placeholders (§11).

## Scoring (§14, §15)

[`RiskScoringService`](../../backend/app/identity/protection/detection.py) sums fixed
weights and caps at 100 — a transparent, testable function, <50ms and side-effect free:

| Signal | Weight | | Signal | Weight |
| ------ | -----: | - | ------ | -----: |
| new_device | +20 | | blocked_ip | +80 |
| new_country | +30 | | suspicious_user_agent | +25 |
| impossible_travel | +40 | | recent_password_reset | +10 |
| failed_attempts > 3 | +20 | | account_newly_created | +10 |
| failed_attempts > 5 | +40 | | old_inactive_account | +20 |

## Levels → action (§14)

| Score | Level | Baseline action |
| ----- | ----- | --------------- |
| 0–20 | LOW | Allow |
| 21–50 | MEDIUM | Allow + log |
| 51–75 | HIGH | Challenge |
| 76–90 | CRITICAL | Require MFA / lock |
| 91–100 | SEVERE | Block + security review |

Thresholds are settings (`PROTECTION_RISK_CHALLENGE_AT` / `_LOCK_AT` / `_BLOCK_AT`), so a
deployment can tune posture without a code change. Admin
[protection rules](./identity-protection-rules.md) then override the baseline.

Every scored attempt is written to `identity_risk_events` with its signals, so an
analyst can see *why* an attempt scored what it did (Settings → Security → Risk events).

## Adaptive rate limiting (§10)

`AdaptiveRateLimitService.adjusted_limit(base, level)` tightens the per-endpoint limit
as risk rises: HIGH −50%, CRITICAL/SEVERE −80%. The counting itself stays in the
Postgres-backed limiter.

## CAPTCHA (§28)

`CaptchaService` is a provider-agnostic seam (Turnstile / reCAPTCHA / hCaptcha) that is
**disabled by default**. `should_challenge` fires on ≥3 failed attempts, risk ≥ 50, or a
suspicious/blocked source; `verify` is a placeholder until a provider is wired.

## Related

- [Account protection overview](./account-protection.md)
- [Brute-force protection](./brute-force-protection.md)
- [Identity protection rules](./identity-protection-rules.md)
