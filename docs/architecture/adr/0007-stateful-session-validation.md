# ADR-0007 — Validate the session on every authenticated request

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Platform engineering
- **Supersedes:** the stateless-hot-path decision in [ADR-0003](./0003-stateless-jwt-with-rotating-refresh-tokens.md)

## Context

[ADR-0003](./0003-stateless-jwt-with-rotating-refresh-tokens.md) chose a stateless
access token: `authenticate` verified the JWT signature and expiry and never
touched the database. It named the cost explicitly — *"revocation is not
immediate"* — and accepted it, bounded to the 15-minute token TTL. That gap was
pinned by a test and written into the threat model.

Part 4.2.2.2 requires behaviour the stateless design cannot deliver:

- §16 — logout must **invalidate the access token**, not merely the refresh token.
- §5, §12 — **idle timeout** (30 min) and **absolute timeout** (12 h) must be
  *enforced*. Enforcement means checking, on request, when the session last saw
  activity. There is nowhere else to check it.
- §9 — on refresh-token reuse, the session is terminated and the user is forced to
  re-authenticate. If the thief's access token keeps working for 15 minutes, we
  have detected the theft and done nothing about it for 15 minutes.
- §17 — an administrator revoking a compromised employee's session expects that
  session to stop, now.
- §28 — the performance budget names *"session lookup: <20ms"*, which only makes
  sense if a session lookup happens on the request path.

The residual risk ADR-0003 accepted is exactly the risk this part exists to close.

## Options considered

### Option A — Keep the stateless hot path; shorten the access-token TTL
- Pros: no per-request database read. No change to the authentication dependency.
- Cons: does not *enforce* idle timeout at all — nothing observes activity. Shrinking
  the TTL to make revocation "fast enough" (say 60 s) multiplies refresh traffic by
  15× and moves the same database read to the refresh endpoint, where it is now paid
  far more often. It trades a cheap read for an expensive round-trip and still never
  reaches immediacy.

### Option B — Token denylist consulted on each request
- Pros: preserves the *idea* of statelessness; only revoked tokens need storage.
- Cons: still a read per request, so the claimed benefit is illusory. Under
  [ADR-0002](./0002-postgresql-as-sole-datastore.md) (no Redis) the denylist is a
  Postgres table anyway. Worse, a denylist answers only "was this token revoked?" —
  it cannot answer "has this session been idle for 31 minutes?", so idle and absolute
  timeouts remain unimplementable. Strictly less capable than Option C at the same cost.

### Option C — Load and revalidate the session on every authenticated request
- Pros: one primary-key lookup answers every question at once — revoked? expired?
  idle? suspicious? device blocked? Logout, force-logout, timeout and theft response
  all become immediate. The session row already exists; nothing new is stored.
- Cons: a database read on the hot path. The API is no longer stateless *in the
  strict sense*, though it remains stateless in the sense that matters for scaling
  (no in-process state; any replica can serve any request).

## Decision

We chose **Option C**.

**Both** authentication dependencies enforce it. `identity.auth.dependency.authenticate`
(the `/api/v1/auth` surface) and `app.api.deps.get_current_user` (the legacy surface,
which still serves `/dashboard`, `/agents`, `/policies`, `/approvals`, `/audit` and the
identity admin API) both load `auth_sessions` by primary key and call
`SessionLifecycleService.assert_usable` whenever the token carries a `session_id`.

That single call rejects revoked, terminated, suspicious, absolutely-expired and
idle-expired sessions with distinct error codes, and slides the idle deadline forward
on success.

Enforcing it in only one dependency would have been worse than not enforcing it at
all: logout would appear to work while every business endpoint kept serving the
revoked token. Pinned by `test_revoked_session_is_rejected_by_legacy_endpoints_too`.

Tokens with **no** `session_id` skip the check — the legacy `/auth/login` token, which
never created a session. It therefore remains non-revocable: a property of that *login
route*, not of either dependency, and it disappears when
[ADR-0005](./0005-additive-identity-layer-alongside-legacy-auth.md) completes.

MFA-challenge tokens do carry no session, but they are rejected outright rather than
waved through: they prove only the primary factor. `require_scope`/`require_assurance`
reject them on the new surface, and `decode_access_token` refuses them on the legacy one.

Option B was rejected as strictly dominated: same cost, fewer capabilities.

## Consequences

### Positive
- **Revocation is immediate.** Logout, admin force-logout, device block and
  token-reuse termination all take effect on the very next request.
- Idle and absolute timeouts are enforceable at all, which they were not before.
- One lookup answers five questions. The alternative designs each answer one.
- The error is *specific*: `SESSION_REVOKED` vs `SESSION_IDLE_TIMEOUT` vs
  `SESSION_EXPIRED` vs `SESSION_SUSPICIOUS`. A client must tell "you were logged
  out" apart from "you idled out" apart from "we think your token was stolen",
  because each demands a different UX.
- Removes the single most-cited weakness from the threat model and lets us delete
  the "known gap" note rather than explain it to every auditor.

### Negative / accepted cost
- **One database read per authenticated request.** Measured against local Postgres
  (n=200, warm pool):

  | | p50 | p95 | max |
  | --- | --- | --- | --- |
  | Session PK lookup | 0.66 ms | **1.35 ms** | 2.91 ms |
  | Whole `GET /auth/me` (JWT verify + lookup + RBAC) | 6.1 ms | 10.6 ms | 11.0 ms |

  Comfortably inside the SRS §28 budget of <20 ms for the lookup. But it is not
  free, and it couples request latency to database health. Under
  [ADR-0002](./0002-postgresql-as-sole-datastore.md) that read hits the primary.
- **A write, sometimes.** Sliding the idle window updates `last_activity_at`. This is
  throttled to at most once per `SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS` (60 s per
  session) — without the throttle, a busy client turns a read-mostly path into a
  write-mostly one and its own concurrent requests contend on one row. The cost of
  the throttle is that the effective idle timeout may overshoot by up to 60 s.
- Postgres is now on the critical path for *authentication*, not just for data. A
  database outage previously degraded the product; it now also prevents login and
  invalidates nothing gracefully.
- The word "stateless" can no longer be used about this API without qualification,
  and ADR-0003's headline is now misleading in isolation. Hence this supersession.
- `decode_access_token` had to be widened to accept the new token's `iss`/`aud` claims.
  It validates them when present rather than disabling the check — a token minted for a
  different audience must still be refused. It also now rejects refresh tokens and
  MFA-challenge tokens outright on the legacy path.

### Residual risk
An access token remains valid for the window between the session being revoked and
the token's *next use* — which is to say, it is valid until someone tries to use it,
at which point it is refused. There is no window of *successful* use. The only
remaining exposure is the legacy `/auth/login` surface, whose 24-hour tokens carry
no `session_id` and are therefore still not revocable at all. **That is now the
platform's worst case, and it is the strongest argument yet for completing
[ADR-0005](./0005-additive-identity-layer-alongside-legacy-auth.md).**

The session lookup is also a new denial-of-service surface: an attacker with a
valid-looking JWT forces a database read per request. Rate limiting
([threat model P0](../security/threat-model.md#prioritised-remediation)) covers this,
and does not exist yet.

## Revisit when

- The session read shows up in p95 latency. First move is a covering index or a
  short-TTL in-process cache keyed by `session_id` — accepting a bounded revocation
  delay equal to the cache TTL, which reintroduces exactly the trade-off this ADR
  removed. Do it consciously or not at all.
- A second datastore is introduced for any reason: revisit
  [ADR-0002](./0002-postgresql-as-sole-datastore.md) and move this read off the primary.
- The legacy surface is retired: delete the `session_id is None` escape hatch in
  `_validate_session` and make the session check unconditional.
