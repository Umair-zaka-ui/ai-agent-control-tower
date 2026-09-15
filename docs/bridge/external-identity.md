# External-agent identity — scoped, revocable, and never internal

Phase 5.7 / M5.7. See also [the gateway](gateway.md), [enforcement
modes](enforcement-modes.md) and
[ADR-0021](../architecture/adr/0021-truthful-external-enforcement-modes.md).

An agent outside ACT must prove who it is before ACT will authorize anything
for it — and it must **never** become an internal principal in the process.

## Why not federation

OIDC/SAML was the obvious candidate and is the wrong tool.
`FederationService._resolve_or_provision_user()` → `_provision_user()` creates a
`User` row, maps group claims onto roles, and `_issue_session()` issues a
session. Every federated login therefore mints an internal principal carrying
internal authority — precisely the privilege escalation this phase forbids.

Federation stays what it is: human and internal SSO.

## Why not a bearer API key

`AgentApiKey` is a bearer credential — whoever holds the string is the agent. A
bearer token **cannot be replay-protected**, because the token is the request's
only proof, so a captured request replays perfectly. It also carries no
capability scope and no rate limit.

## What ACT uses instead: signed requests

The agent holds a secret that is never transmitted, and signs each request:

```
ACT-HMAC-SHA256
<METHOD>
<path>
<unix-timestamp>
<nonce>
<sha256-hex-of-the-exact-body-bytes>
```

HMAC-SHA256 over that string, hex-encoded, sent as `X-ACT-Signature` alongside
`X-ACT-Key-Id`, `X-ACT-Timestamp` and a fresh `X-ACT-Nonce`.

The body is reduced to a **digest of the exact bytes received**, not a
re-serialization of a parsed model — re-encoding JSON before verifying is where
cross-language signing schemes quietly break. ACT reads the raw body in an
async dependency and verifies against those bytes.

That gives four properties at once:

- **Identity without a `users` row.** The grant names an `agents` row and
  nothing else. No role, no session, no token any other ACT surface accepts.
- **Replay protection.** A ±300s timestamp window plus a `(grant_id, nonce)`
  unique constraint. The database is the primitive, not a cache, so two
  concurrent replays cannot both commit.
- **Scope.** The grant lists the capabilities and targets it may reach. That
  list *bounds* reach; it never grants authority. Authority is decided by
  `AuthorizationGateway` on every single call.
- **Revocation.** Immediate and unconditional — every call re-reads the grant
  row, and nothing about a grant is cached anywhere.

Verification order is deliberate: cheap structural checks, then the HMAC, then
the nonce write **last**. A request that fails verification must not be able to
consume a nonce, or an attacker could burn a legitimate caller's nonces with
garbage signatures.

## The grant

`external_capability_grants` — one row per credential:

| Field | Purpose |
|---|---|
| `key_id` | the public identifier the caller sends; safe to log and audit |
| `secret_ciphertext` | Fernet ciphertext via M4.11 `credential_crypto`; the plaintext is returned **once**, at issue, and is never retrievable |
| `secret_hint` | a masked hint for the UI, never enough to reconstruct the secret |
| `scope` | `[{"capability": ..., "target_ref": ...}]` |
| `expires_at` / `revoked_at` | lifecycle |
| `rate_limit_per_minute` | per-grant abuse bound |

Issuing requires `external_grant.issue` — a distinct, stronger permission never
implied by view or manage.

**A grant scoped to a *governed* capability can only be issued to an agent
whose effective mode actually enforces boundary calls.** Issuing one to an
`OBSERVED` or `ADVISORY` agent is refused (`EXTERNAL_MODE_DOES_NOT_ENFORCE`):
it would be a credential for a boundary that, for that agent, enforces nothing
— the exact shape of an over-claim.

**An evidence-only scope (`telemetry.ingest`) is allowed in every mode**, and
that is not an inconsistency. Ingesting evidence enforces nothing and implies
no control, so such a credential claims nothing; refusing it would instead
leave `OBSERVED` — the mode whose entire content is "ACT sees this agent" —
with no way to be seen. The two rules are the same rule: a credential may
never imply enforcement ACT does not have.

Scope is enforced on both boundary endpoints. `/events` refuses a grant not
scoped for `telemetry.ingest` (`EXTERNAL_SCOPE_DENIED`, 403) — fail-open
governs how a malformed or unstorable *event* is treated, never **who** may
write one.

## Blast radius

A compromised grant costs the attacker exactly the scoped capabilities, on one
agent, in one tenant, for as long as it takes an operator to revoke it.

It cannot be escalated into internal identity by any path, because there is no
path: nothing in `app/bridge` imports the federation service, the registration
service or the session service, and nothing calls `provision`,
`_issue_session` or `create_access_token`
(`test_ac16_no_internal_identity_no_new_authz_no_parallel_enforcer`).

Errors are deliberately indistinct at the edge — an unknown `key_id` and a bad
signature both return the same `EXTERNAL_SIGNATURE_INVALID`, so a prober cannot
learn which key ids exist. Cross-tenant access returns 404, never 403.

## Nothing secret is ever logged

The audit trail records the `key_id`, the scope and the decision. It never
records the secret, its ciphertext or its hint — asserted directly against the
audit table, the grant row, the gateway records and the API read model
(`test_ac13_no_secret_or_token_appears_in_audit_or_records`).
