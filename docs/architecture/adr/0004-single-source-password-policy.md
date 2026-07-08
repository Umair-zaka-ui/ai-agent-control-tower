# ADR-0004 — One password policy, defined once, argon2id

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Platform engineering
- **Supersedes:** —

## Context

Part 4.2.2.1 shipped a `PasswordService` with a strong policy: ≥12 characters,
four character classes, a common-password blocklist, and rejection of passwords
containing the user's email local-part or username.

An audit against the acceptance criteria found that **`PasswordService` was never
called from production code.** Its only references were its own module export and
the tests. Three routes set passwords, and each did something different:

| Path | Enforcement before |
| ---- | ------------------ |
| `POST /auth/register` | none — `hash_password()` directly, Pydantic `min_length=8` only |
| `POST /users` | none — same |
| `IdentityService.create_user` | a *second*, weaker policy in `identity/security/passwords.py` (8 chars, mixed case, one digit) |

Two divergent policies existed, and the weaker one was the only one that ran. The
test suite itself registered users with `password123` — a password the documented
policy forbids.

The root cause was structural, not carelessness. `PasswordService` lives in
`app/identity/auth/`. The low-level module that needs the policy,
`app/identity/security/passwords.py`, is imported **at module scope** by
`identity/auth/credential_service.py` and `identity/tokens/service.py`. Making
`security/passwords.py` call *up* into `identity.auth` creates an import cycle.
So the policy got re-implemented at the layer where it was convenient to write,
and never wired into the layer where it was needed.

## Options considered

### Option A — Break the cycle with function-level imports
- Pros: minimal diff; `PasswordService` stays the definition.
- Cons: hides a real layering violation behind a deferred import. The next person
  to add a module-scope import re-breaks it. Cycles you can't see are worse than
  cycles you can.

### Option B — Validate in Pydantic schemas (`min_length`, a validator)
- Pros: fails fast, before the service layer; automatic OpenAPI documentation.
- Cons: the policy then lives in *every* schema that accepts a password, which is
  the original bug wearing a different hat. Nothing stops a service-layer caller
  (seed scripts, admin tooling, future SSO provisioning) from bypassing it.

### Option C — Define the policy in the lowest module, facade above it
- Pros: single definition, no cycle, enforceable at the one function every caller
  must go through. Layering points the right way.
- Cons: the policy lives in `security/`, not in the `PasswordService` that appears
  to own it — mildly surprising until you know about the cycle.

## Decision

We chose **Option C**.

- The policy is defined **once** in `app/identity/security/passwords.py`.
- `hash_user_password(password, *, email, username)` validates then argon2id-hashes.
  It is the only sanctioned way to set a human password.
- `PasswordService` becomes the thin facade its own docstring already claimed to
  be, delegating to that module.
- All three password-setting paths now call `hash_user_password`.
- A `PasswordPolicyError` handler maps to **HTTP 422** globally — without it, the
  newly-raised error would have surfaced as a 500 on the legacy routes.
- Pydantic `min_length` was raised 8 → 12, but it is explicitly *not* the policy.
  The regression tests use long-but-weak passwords (`alllowercase123!`) to prove
  the complexity check, not the length floor, is doing the work.

Hashing is **argon2id**, with pre-existing bcrypt hashes verified and transparently
re-hashed on next successful login. The re-hash path deliberately skips validation:
a user whose password predates this policy must still be able to log in.

Option B was rejected because it optimises for the HTTP boundary while leaving
every non-HTTP caller unprotected — and `app/seed.py` is exactly such a caller.

## Consequences

### Positive
- One policy. Changing it means editing one function.
- Impossible to set a human password without validation: there is no other path to
  a `password_hash`.
- Weak passwords return a structured `422`, not a `500`.
- Enforced at the **routes**, which is where the original bug hid. The regression
  tests exercise `POST /auth/register` and `POST /users`, not `PasswordService` in
  isolation — a unit test on the service would have passed throughout the bug's life.

### Negative / accepted cost
- The policy's home is counter-intuitive. Mitigated by a comment in both modules
  explaining the cycle, but a reader looking for it in `PasswordService` will be
  briefly confused.
- Tightening the policy invalidated fixtures across **12 test files** plus
  `app/seed.py` and two README references. Any future tightening carries the same
  cost.
- Existing users with policy-violating passwords are unaffected — the policy binds
  only at *set* time. There is no forced-rotation mechanism.

### Residual risk
The blocklist is 16 entries. It catches `Password123!` via alphanumeric
normalisation, but it is not a breached-password corpus. `_is_common` is the seam
for a HaveIBeenPwned k-anonymity check; until that lands, a determined user can
still choose a password that is weak-in-practice while passing every rule.

## Revisit when

- Before the first enterprise deployment: add breached-password checking via the
  `_is_common` seam.
- If password-set latency becomes noticeable, review argon2id parameters — they are
  currently passlib defaults and have not been tuned to this hardware.
- If SSO lands and local passwords become a fallback path rather than the primary
  one, the policy's cost/benefit changes.
