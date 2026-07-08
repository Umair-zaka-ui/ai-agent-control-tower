# ADR-0005 — Build the identity layer additively, beside legacy auth

- **Status:** Accepted *(retroactively recorded 2026-07-08; decision made in Phase 4 Part 4.2.1)*
- **Deciders:** Platform engineering
- **Supersedes:** —

## Context

Phases 1–3 shipped a working authentication system: `POST /auth/login` returns a
24-hour HS256 JWT with no session record and no refresh token. The dashboard SPA,
every API route, the agent-action pipeline and the full test suite depend on it.

Phase 4 requires an enterprise identity platform: sessions, refresh-token rotation,
reuse detection, account lockout, login history, security events, assurance levels
(AAL0/1/2), and seams for MFA, SSO, device trust and external IdPs.

The legacy design cannot be extended into that. A 24-hour non-revocable token has
no session to revoke, no assurance level to elevate, and no refresh to rotate. The
question is not *whether* to replace it, but *how* — with a live product, a
dependent frontend, and a test suite that assumes the old shape.

## Options considered

### Option A — Big-bang cutover: rewrite `/auth/login` in place
- Pros: one auth system at all times. No confusing duplication. Shortest total path.
- Cons: every route, the SPA, and ~100 tests change in a single PR. The blast radius
  of a mistake is *the entire product's ability to authenticate*. Impossible to
  ship incrementally; impossible to roll back cleanly once the SPA is updated.

### Option B — Version the whole API (`/api/v2/*`) and port routes across
- Pros: clean separation; clients migrate on their own schedule.
- Cons: duplicates 15 routers to change one concern. The problem is authentication,
  not the API surface. Enormous diff, mostly noise.

### Option C — New auth surface beside the old, sharing the credential check
- Pros: legacy path untouched and green throughout. New surface can be built,
  tested and hardened against real traffic before anything migrates. Route-by-route
  cutover, each independently revertible.
- Cons: **two authentication systems in production simultaneously**, with different
  security properties. The weaker one sets the platform's true worst case.

## Decision

We chose **Option C**.

- `/api/v1/auth/*` (new) and `/auth/*` (legacy) coexist.
- `AuthenticationService.login` calls the legacy `auth_service.authenticate_user`
  for credential verification, then builds a session, refresh token and
  `IdentityContext` on top. **The credential check is shared; everything above it
  is new.** That shared call is the migration seam.
- New capabilities land only on the new surface. The legacy surface is frozen —
  it receives security fixes (e.g. [ADR-0004](./0004-single-source-password-policy.md)
  wired the password policy into `/auth/register`) but no features.
- Machine authentication on `/api/v1` deliberately **fails closed** with
  `API_KEY_INVALID` rather than silently falling back to the legacy path.

Option A was rejected on risk, not effort. Authentication is the one subsystem
where a bad deploy locks out every user *and* every engineer trying to fix it.

## Consequences

### Positive
- Legacy tests stayed green through the entire Phase 4 identity rebuild.
- The new stack was exercised end-to-end (login, rotation, reuse detection,
  lockout, session listing) before any client depended on it.
- Migration is route-by-route and reversible. No flag day.
- The seam is explicit and greppable: one call from `AuthenticationService.login`
  into `app.services.auth_service`.

### Negative / accepted cost
- **The platform's real worst-case session lifetime is 24 hours, not 15 minutes.**
  A token minted by `/auth/login` carries no session, cannot be revoked, and
  outlives logout, suspension and role changes. The new surface's careful
  revocation story is only as strong as the weakest surface still accepting logins.
- Duplicate concepts, visibly: `users.role` (legacy enum) *and* `user_roles` (RBAC);
  `agents.api_key_hash` (Phase 1) *and* `agent_api_keys` (Phase 2). Both pairs are
  live. New code must know which to use.
- Two login endpoints is a genuine footgun for anyone integrating today.
- Reviewers repeatedly ask "why are there two?" — which is the direct reason this
  ADR exists.

### Residual risk
The migration may stall. Additive migrations are easy to start and easy to leave
half-finished, and the legacy surface works well enough that nothing forces the
issue. If it stalls, the platform permanently carries a non-revocable 24-hour
credential — while its documentation advertises 15-minute tokens with rotation and
reuse detection. **That gap between the marketed and the actual security posture is
the real risk of this decision**, and it grows the longer the migration takes.

Tracked as a P2 in the [threat model](../security/threat-model.md#prioritised-remediation).

## Revisit when

- **Trigger to complete:** the SPA no longer calls `/auth/login`. At that point
  delete the legacy route, drop `ACCESS_TOKEN_EXPIRE_MINUTES`, and supersede this ADR.
- **Trigger to escalate:** any external integrator adopts `/auth/login`. Freezing a
  surface is easy; deprecating one with third-party consumers is not.
- If Phase 5 begins with the legacy surface still live, that should be treated as a
  planning failure and scheduled explicitly rather than deferred again.
