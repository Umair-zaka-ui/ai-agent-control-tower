# Password Policy (Phase 4 Part 4.2.2.3.2)

> One place decides what a password must be. The API, the meter and the enforcer
> all read it, so they cannot drift apart.

## Single source (ADR-0004)

The policy lives in [`app/identity/security/passwords.py`](../../backend/app/identity/security/passwords.py).
`PasswordPolicyService` and `PasswordService` are thin facades over it; the frontend
meter ([`passwordStrength.ts`](../../frontend/src/modules/identity/passwordStrength.ts))
*mirrors* it for instant feedback but is never the gate — a password that passes the
meter can still be refused with a 422, and the form renders that.

## The rules (§6, §7)

| Rule | Default | Why |
| ---- | ------- | --- |
| Length | 12–128 | Length dominates entropy |
| Uppercase / lowercase / number / special | all required | Character diversity |
| Spaces | allowed | Passphrases are good passwords |
| Not a common password | blocklist + **prefix** match | `password123!AA` is not saved by two extra characters |
| No sequences | `1234`, `qwer`, `dcba` (runs of 4) | The first things a guesser tries |
| No 4× repeats | `aaaa` | Same |
| Not your identity | name · email local-part · username · **organization name** | A password built from public facts is not secret |

Common-password matching is **prefix**, not contains-anywhere: people decorate a weak
password by *appending* (`password123!AA`), so a prefix catches that, while a strong
password that merely embeds a stem mid-string (`T3st!Passw0rd#Ok`) is not punished.

Every rejection carries a machine code (`PASSWORD_TOO_WEAK` / `PASSWORD_POLICY_FAILED`,
§26) so the client can react precisely.

## Strength, for display (§8)

`estimate_strength()` returns `{level, score 0–4, meets_policy, entropy_bits, feedback}`
across five levels — **very weak · weak · fair · strong · very strong**. It is advisory:
a password that fails the gate can never be scored above *weak*, so the meter never tells
a user a rejected password is fine. `POST /api/v1/auth/validate-password` exposes it
(rate limited, §25); the SPA also computes it locally for zero-latency feedback.

## Storage (§9)

argon2id, via passlib, with transparent upgrade of any legacy bcrypt hash on next login
(audited as `PASSWORD_ROTATED`). Salt and parameters are encoded in the hash string; we
never store plaintext, and an SSO/SCIM identity carries the `UNUSABLE_PASSWORD` sentinel
so no password can verify against it.

## Configuration

`GET /api/v1/auth/password-policy` returns the active policy as data (lengths, class
requirements, history depth, `max_age_days`, `min_age_hours`, warning windows,
temp-password TTL). All tunable in [`config.py`](../../backend/app/core/config.py);
per-organization policy is a documented future seam (§5).

## Related

- [Credential management](./credential-management.md)
- [Password history](./password-history.md)
