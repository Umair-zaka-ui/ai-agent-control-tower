# ADR-0003 — Stateless JWT access tokens with rotating refresh tokens

- **Status:** **Partially superseded by [ADR-0007](./0007-stateful-session-validation.md)** *(retroactively recorded 2026-07-08; decision made in Phase 4 Part 4.2.1)*
- **Deciders:** Platform engineering
- **Supersedes:** —

> **Superseded in part (2026-07-08).** The token *shapes* decided here — a 15-minute
> JWT access token plus a 7-day opaque, single-use, rotating refresh token with
> reuse detection — remain in force and are unchanged.
>
> What is superseded is the **stateless hot path**: as of Part 4.2.2.2 the session
> behind an access token is loaded and revalidated on every authenticated request,
> so the "revocation is not immediate" cost accepted below no longer applies to the
> `/api/v1/auth` surface. See [ADR-0007](./0007-stateful-session-validation.md).
>
> This document is left intact rather than edited: the reasoning that led to the
> original trade-off is the point of keeping it.

## Context

Human sessions need an authentication credential presented on every request. The
platform must support logout, session listing, remote session revocation, and
detection of stolen credentials — and it must be able to grow into MFA, SSO and
device trust without a redesign.

Two properties are in direct tension:

1. **Statelessness** — an access token that can be validated without touching the
   database keeps the hot path cheap and lets the API scale horizontally.
2. **Immediate revocation** — a credential that can be killed the instant a
   session is revoked requires checking shared state on every request.

You can have one cheaply. You cannot have both.

## Options considered

### Option A — Opaque session tokens, looked up in the DB on every request
- Pros: immediate revocation. Logout means logout. Session state is authoritative.
- Cons: a `sessions` SELECT on **every** authenticated request. Couples request
  latency to the database. Under [ADR-0002](./0002-postgresql-as-sole-datastore.md)
  (no Redis) that read hits the primary.

### Option B — Long-lived stateless JWT, no refresh token
- Pros: simplest possible. This is what the legacy `/auth/login` does today
  (24-hour token, `ACCESS_TOKEN_EXPIRE_MINUTES=1440`).
- Cons: a stolen token is valid for a day. No revocation of any kind. No theft
  detection. Not acceptable for an enterprise control plane.

### Option C — Short-lived stateless JWT + long-lived, rotating, stateful refresh token
- Pros: hot path stays stateless (signature + expiry only). Revocation is bounded
  by the access-token TTL. The refresh exchange is a natural, low-frequency place
  to consult the database. Rotation gives **theft detection** for free: a replayed
  token proves compromise.
- Cons: revocation is not immediate — a revoked session's access token remains
  valid until it expires. Two credential types to reason about.

## Decision

We chose **Option C**.

- Access token: JWT, HS256, **15 minutes** (`AUTH_ACCESS_TOKEN_TTL_SECONDS`),
  carries the full identity claim set (`roles`, `permissions`, `assurance_level`,
  `amr`, `session_id`). Validated by signature and expiry alone.
- Refresh token: opaque `rt_…`, **7 days**, stored as a SHA-256 hash, **single-use**.
  Every use revokes it and issues a successor, chained via `rotated_to_id`.
- Presenting an already-rotated token is treated as theft: the token family **and
  the session** are revoked, and `REFRESH_TOKEN_REUSED` is recorded.

Option A was rejected on cost: it puts a DB read on every request to buy
revocation latency we can instead bound to 15 minutes. Option B is what we are
migrating *away* from ([ADR-0005](./0005-additive-identity-layer-alongside-legacy-auth.md)).

## Consequences

### Positive
- Authenticated requests do no database work for authn beyond signature verification.
- The API is stateless → horizontally scalable once migrations move out of the
  entrypoint ([deployment gap 8](../deployment/deployment.md#gaps-before-production)).
- Rotation converts refresh-token theft from *undetectable* to *self-announcing*:
  the thief and the victim cannot both refresh. The second one to try is evicted.
- The refresh exchange is the natural seam for future device-trust and step-up
  re-evaluation, because it is the only place we already touch session state.

### Negative / accepted cost
- **Revocation is not immediate.** Logout, session revocation, and reuse detection
  all revoke the *session*, stopping new tokens — but an access token already
  issued keeps working until it expires. `dependency.authenticate` validates the
  JWT and never loads the session.

  | Surface | Worst case after revocation |
  | --- | --- |
  | `/api/v1/auth` | 15 minutes |
  | legacy `/auth/login` | 24 hours (no session at all) |

- Reuse detection logs out the **victim** as well as the thief. This is intended —
  an interrupted session is strictly better than a hijacked one — but it is a real
  UX cost and will generate support tickets.
- Two token types means two failure modes to explain to integrators.

### Residual risk
The revocation window is a genuine, exploitable gap: an attacker who steals an
access token retains up to 15 minutes of access *after* we have detected the theft
and killed the session. It is pinned by
`test_access_token_outlives_session_revocation_documented_gap` so it cannot
regress silently, and documented in
[token-strategy.md](../../identity/token-strategy.md) and the
[threat model](../security/threat-model.md#s-spoofing).

Refresh tokens are stored in browser `localStorage`, so an XSS on the dashboard
origin yields a 7-day credential. Rotation bounds the blast radius; it does not
prevent the theft.

## Revisit when

- A regulator, customer, or incident requires **immediate** revocation. The fix is
  a session check or denylist on the hot path — reopen
  [ADR-0002](./0002-postgresql-as-sole-datastore.md) at the same time, because
  that read becomes the most frequent query in the system.
- The legacy 24-hour surface is retired — at that point the platform's worst-case
  window drops from 24 h to 15 min and this trade-off gets much easier to defend.
- MFA is enabled: a rotated refresh token currently re-mints at AAL1 because
  `sessions` carries no persisted `assurance_level` column. That must be fixed
  before step-up is meaningful across a refresh.
