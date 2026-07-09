# Brute-Force Protection (Phase 4 Part 4.2.2.3.4 §9)

> The same failed-login stream drives three different detectors, because "many
> failures" means different things depending on what varies: the account, the source,
> or the target set.

## Patterns (§9)

[`BruteForceDetectionService`](../../backend/app/identity/protection/detection.py) reads
`login_history` failures within the lockout window and reports:

| Pattern | Signal | Meaning |
| ------- | ------ | ------- |
| `account_attack` | ≥ `PROTECTION_FAILED_THRESHOLD` failures for one email | someone is hammering one account |
| `ip_brute_force` | ≥ `PROTECTION_BRUTEFORCE_IP_THRESHOLD` failures from one IP | a noisy source |
| `credential_stuffing` | one IP failed against ≥ `PROTECTION_STUFFING_DISTINCT_ACCOUNTS` distinct accounts | leaked-credential replay across many users |

```
same account + many failures      → account attack
same IP + many accounts           → credential stuffing
many failures from one IP         → IP brute force
```

## What a detection does

Detection is separate from enforcement. On a failed login, `record_failure`:

1. Emits the matching audit event — `BRUTE_FORCE_DETECTED` or
   `CREDENTIAL_STUFFING_DETECTED` — so the pattern is visible even before a lock.
2. Chooses the **lock reason** accordingly when the account's own failures cross the
   threshold: a stuffing pattern locks with `CREDENTIAL_STUFFING_SUSPECTED`, a noisy IP
   with `BRUTE_FORCE_DETECTED`, otherwise `FAILED_LOGIN_THRESHOLD`.

The lock itself is progressive — see [account-lockout.md](./account-lockout.md).

## Blocking a source (§16)

A security admin can block an IP outright (Settings → Security → Blocked IPs). A block
is checked in `pre_check`, *before* the password, so a blocked source cannot even burn
argon2id CPU. Blocks are org-scoped or global, and can be permanent or lapse after a set
number of minutes. Blocking and unblocking are audited (`IP_BLOCKED` / `IP_UNBLOCKED`).

## Rate limiting (§10, §15)

All public auth endpoints (login, forgot/reset password, verify/resend, invitation
accept) are Postgres-backed rate limited. Under risk the effective limit tightens (see
[risk-based-authentication.md](./risk-based-authentication.md#adaptive-rate-limiting-10)).

## Related

- [Account protection overview](./account-protection.md)
- [Account lockout](./account-lockout.md)
