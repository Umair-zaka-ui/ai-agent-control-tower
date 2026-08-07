# External Identity Federation (Phase 2.3.1, `ACT-INT-FR-180..187`)

> **The platform never stores a federated user's credential.** It verifies a
> signed assertion from the enterprise's own IdP and trusts it — the
> password, MFA factor, or whatever else the IdP required stays entirely
> with the IdP, forever. This is the entire security value of federation,
> not a limitation of it.

This is Milestone 2's ninth and final sub-phase — the one that completes
the **Enterprise Integration Framework**. Every prior sub-phase (2.1.x's
framework, 2.2.1–2.2.4's four generic connectors) authenticated **the
platform to** an external system. This one runs the opposite direction:
an enterprise's own IdP authenticates **a user to the platform**.

## The inversion, and why it drives the whole design

| | Connectors (2.1.2, 2.2.x) | Federation (2.3.1) |
|---|---|---|
| Who is the authority | the platform | the IdP |
| What the platform holds | a secret, encrypted, presented outward | nothing of the user's |
| Direction | platform → external system | IdP → platform |
| Failure mode defended against | leaking the platform's own credential | forging or replaying the IdP's assertion |

`ACT-INT-FR-186` — never store a federated user's external credential — is
the defining rule. An enterprise's security team will not hand a
third-party platform their employees' passwords; federation means this
platform never has to ask. `ACT-INT-FR-182` is the second, equally weighted
rule: a federated identity maps into the platform's **existing** user and
RBAC model (Phase 4.x) — never a second, parallel identity system.

## What is, and is not, stored

| Stored | Where | Secret? |
|---|---|---|
| IdP endpoints, issuer, JWKS URI, SAML certificate | `identity_federation_configs.configuration` | No — public verification material, integrity-critical but not confidential |
| The platform's **own** OIDC client secret (if the IdP requires one) | `identity_federation_configs.encrypted_client_secret` | Yes — encrypted via the same `credential_crypto.py` Fernet key every other platform-held secret in this codebase already uses |
| The link between an IdP subject and a platform user | `federated_identities.external_subject_id` | No — a stable identifier, not a credential |
| The user's password, MFA factor, or any credential the IdP verified | **nowhere** | — |

`federated_identities` has no credential column of any kind — not because
one is left empty, but because the platform never receives anything to
put in one. The verified assertion establishes a session and is then
discarded; nothing about *how* the user proved their identity to the IdP
survives past that.

## OIDC — authorization-code flow

Standard flow: redirect to the IdP → the user authenticates *at the IdP*
→ the IdP redirects back with a code → the platform exchanges the code
for an ID token at the IdP's token endpoint → **the ID token's signature
is verified against the IdP's own JWKS** → issuer/audience/expiry/nonce
are all checked → identity claims are extracted.

### The security core, and the library choice

`app/identity/federation/oidc.py::verify_id_token` is pure — no HTTP, no
database — and is the only place a token's trustworthiness is decided.
It reuses **`python-jose`**, already a platform dependency (it signs the
platform's own access tokens), "with care" rather than hand-rolled, per
this phase's own build prompt allowance. "With care" means, concretely:

- **The accepted algorithm set is fixed by this organization's own stored
  configuration, never taken from the token's own `alg` header.** This is
  what closes the classic JWT "algorithm confusion" bypass — an attacker
  crafting an HS256 token, hoping a careless verifier reads `alg` from the
  token and uses the RSA public key bytes as an HMAC secret. Proven
  directly: `test_oidc_bypass_prevention.py` mints exactly that attack
  token (and a bare `alg: none`, unsigned token) and asserts both are
  rejected.
- **The signing key is resolved from the IdP's own JWKS by `kid`, never
  trusted from the token.** An unrecognized `kid` is rejected outright —
  there is no "try every key" fallback.
- **Issuer, audience, expiry, and nonce are all explicitly checked.** A
  verified-but-replayed token (a different login attempt's nonce) is
  rejected — this is what defeats presenting an old, legitimately-issued
  ID token against a new login.

Every one of these is a named, cited acceptance criterion with its own
passing test — see `backend/tests/identity/federation/
test_oidc_bypass_prevention.py`.

### CSRF/replay defense without a new "pending requests" table

The backend is stateless between the redirect and the callback — there
is no session yet (that is what this flow is establishing). Rather than
persist a pending login attempt server-side, `FederationService` embeds
everything the callback needs (organization, config, nonce) in a
short-lived, **platform-signed** `state` token (reusing the existing
`JWT_SECRET_KEY`/`JWT_ALGORITHM` — no new secret). Forging a valid state
requires the platform's own signing key; an expired or wrong-purpose one
is rejected before anything else runs.

## SAML 2.0 — web-browser SSO

Standard flow: the platform (SP) redirects to the IdP → the IdP
authenticates and POSTs back a **signed SAML assertion** → the platform
**verifies the assertion's XML signature** against the IdP's configured
certificate → conditions (audience, time bounds, recipient,
`InResponseTo`) are validated → identity attributes are extracted.

### Do not hand-roll XML signature verification

SAML has a well-documented history of signature-bypass classes — XML
canonicalization tricks, and **signature-wrapping attacks** that smuggle
attacker-controlled content next to a validly-signed element, hoping a
naive parser reads the wrong one. `app/identity/federation/saml.py` is a
thin wrapper around **`python3-saml`** (OneLogin's SP toolkit,
`requirements.txt`-pinned), which delegates the actual cryptographic and
DOM work to **`xmlsec`** — a binding over `libxmlsec1`, a security-focused
C library purpose-built for exactly this problem. No XML is parsed or
signature-checked by hand anywhere in this module.

`strict: True` is never optional — every settings dict this module builds
sets it, enabling the toolkit's own schema validation and the additional
security checks non-strict mode relaxes for debugging only.

### Proving the wrapping defense, not just asserting it

`test_saml_bypass_prevention.py` builds **real, `xmlsec`-signed** SAML XML
(via this test suite's own `_saml_fixtures.py` — the only place in this
codebase that ever *constructs* a signed assertion, since the platform is
a verifier, never an issuer) and proves two wrapping shapes are both
rejected:

1. A validly-signed, legitimate assertion sits in the response, and an
   attacker-controlled, **unsigned** assertion (different subject,
   different attributes) is inserted as a sibling ahead of it.
2. The legitimate signed assertion is moved into a `<samlp:Extensions>`
   wrapper (out of the normal processing path), and the forged, unsigned
   assertion takes its place as the response's only direct-child
   assertion.

Both are rejected outright — `python3-saml`/`xmlsec` resolve the element
to trust by following the signature's own `<Reference URI="#...">` back
to the exact element it covers (by ID), never by a separate, weaker
"find the first Assertion" query that a wrapping attack could fool.

### CSRF/replay defense: `RelayState`

The same signed-token scheme OIDC uses for `state`, applied to SAML's own
`RelayState` — with one addition: the outgoing `AuthnRequest`'s own id is
embedded in it, so the response's `InResponseTo` can be strictly checked
against the exact request this login attempt sent (`python3-saml`'s own
`process_response(request_id=...)` enforces the match). This is the
stateless equivalent of a server-side "pending requests" table.

## Mapping to the existing user/RBAC model (`ACT-INT-FR-182`, `FR-183`)

A verified assertion carries a **stable subject identifier** (OIDC `sub`,
SAML `NameID`) plus, optionally, email/name/group claims.

- **The subject id — never email — is the link key.** Email can change
  and can be reassigned by an IdP administrator; a stable, IdP-issued
  identifier cannot silently reattach one platform account to a
  different human.
- **Group/role claims map to platform roles via per-organization
  configuration**, not code (`app/identity/federation/claim_mapping.py`,
  pure, no database): `{"rules": [{"idp_value": "AI-Admins", "role_name":
  "ADMIN"}]}`. A user can match multiple rules and receive multiple
  distinct roles.
- **The result is a normal platform user with normal platform roles**,
  subject to the existing RBAC/ABAC. Nothing downstream — permission
  checks, audit, session listing, force-logout — knows or cares that the
  user authenticated via federation.

### Linking to an existing account vs. provisioning a new one

On first federated login for a given subject id:

1. If that subject is already linked (a `federated_identities` row
   exists), the linked user signs in. This is the common case for every
   subsequent login.
2. Otherwise, if a platform user with the assertion's email **already
   exists** in the same organization, the federated identity is **linked**
   to that existing account — no new user is created. This is the common
   *first*-login case for a real deployment: an org provisions accounts
   (invitations, admin creation) first and turns federation on later.
3. Otherwise, if the organization's `jit_provisioning_enabled` is `true`,
   a brand-new platform user is created via the existing
   `UserProvisioningService` seam (`app/identity/registration/
   provisioning_service.py` — the same seam SSO/SCIM provisioning was
   *designed* for since Phase 4.2.2.3.1, per that module's own docstring)
   and then linked.
4. Otherwise, the login is rejected with `FEDERATION_USER_NOT_PROVISIONED`.

**`jit_provisioning_enabled` gates step 3 only — creating a genuinely new
identity — never step 2, linking to an account that already exists.**
This distinction is deliberate: linking creates no new identity, so there
is nothing for a "should this connector be allowed to provision users"
policy to say no to.

## Session issuance — the existing pipeline, never a parallel one

A federated login terminates in **exactly the same session-issuance
pipeline** a local password login uses —
`SessionLifecycleService.create()` → `RefreshRotationService.issue()` →
`IdentityContextResolver.from_user()` → `TokenService.create_access_token()`
— with `login_method` recorded as `OIDC`/`SAML` instead of `PASSWORD`.
After that call returns, a federated session is **indistinguishable** from
a local one to every other part of this platform: the same
`/api/v1/auth/me`, the same session listing, the same admin force-logout,
the same RBAC/ABAC enforcement. Proven directly:
`test_ac03_a_federated_session_is_indistinguishable_from_a_local_one_via_me`.

**Assurance level is deliberately `AAL1`, never speculatively `AAL2`.**
The IdP may have required MFA before issuing its assertion, but this
platform has no reliable way to introspect that — and the whole point of
federation is that the enterprise's own IdP owns that decision (see
"What federation deliberately does not do," below). Claiming a stronger
assurance level than this platform can actually verify would be
asserting something it cannot stand behind.

## Per-organization configuration, coexistence with local auth

Each organization configures its own IdP connection
(`identity_federation_configs`, one row per `(organization_id, protocol,
provider_type)`) — Entra ID, Okta, or a generic OIDC/SAML IdP, by
configuration, never code. **Local password authentication is completely
unaffected** — federation is an additional login path, not a
replacement; an organization with federation configured, and one without,
and a single organization's own local users alongside its federated
ones, all continue to work exactly as before. Proven directly:
`test_ac04_local_login_still_works_after_federation_is_configured`, and
the entire pre-existing local-auth test suite (`tests/identity/auth/`,
`tests/identity/registration/`, etc.) passes unmodified.

## What federation deliberately does not do

| Excluded | Why |
|---|---|
| Platform-layer MFA for federated users | The enterprise's IdP enforces MFA before issuing its assertion — that is the point of federation. Rebuilding it here would be redundant and would require introspecting IdP-internal policy this platform cannot reliably verify. |
| SCIM directory synchronization (bulk provisioning, deprovisioning, group sync outside of login) | A larger, separate capability. JIT provisioning (create-on-first-login) is in scope; bulk sync is not. |
| Replacing or removing local authentication | `ACT-INT-FR-187` — it coexists, unchanged. |
| A parallel identity/session system | `ACT-INT-FR-182` — federation authenticates into the existing model and issues the existing session type. |
| Any change to model/tool execution or the four generic connectors | Out of this domain entirely — this sub-phase touches identity, not runtime or integration. |

## API

Public login endpoints (unauthenticated by nature — they *establish*
authentication):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/auth/federation/{org}/{config}/login` | Redirect to the IdP |
| GET | `/api/v1/auth/federation/{org}/callback` | OIDC callback (code exchange). `config` is recovered from the verified `state`, not the URL. |
| POST | `/api/v1/auth/federation/{org}/saml/acs` | SAML assertion consumer service. `config` is recovered from the verified `RelayState`. |
| GET | `/api/v1/auth/federation/{org}/{config}/metadata` | SP metadata (SAML) |

Admin configuration (gated by the new `identity.federation.view`/
`identity.federation.manage` permissions, scoped to the caller's own
organization — a config belonging to a different org is a plain 404):

| Method | Path |
|---|---|
| GET / POST | `/api/v1/identity/federation/configs` |
| GET / PUT / DELETE | `/api/v1/identity/federation/configs/{id}` |
| POST | `/api/v1/identity/federation/configs/{id}/test` |

New error codes: `FEDERATION_CONFIG_NOT_FOUND`, `FEDERATION_CONFIG_INVALID`,
`FEDERATION_ASSERTION_INVALID` (the bypass-prevention code — shared by
both protocols, so a caller reacting to a failure never needs to branch
on which one is configured), `FEDERATION_STATE_INVALID` (the CSRF/replay
code), `FEDERATION_USER_NOT_PROVISIONED`, `FEDERATION_CLAIM_MAPPING_FAILED`.

## Testing

`backend/tests/identity/federation/`:

- `test_oidc_bypass_prevention.py` (14 tests) — the OIDC security core,
  against a real, freshly-generated RSA keypair, with no live IdP, no
  HTTP, no database anywhere in the file. Every named attack class:
  tampered signature, wrong key, algorithm confusion, `alg: none`,
  expired, wrong audience, wrong issuer, replayed/mismatched/missing
  nonce, unrecognized `kid`.
- `test_saml_bypass_prevention.py` (12 tests) — the SAML security core,
  against real `xmlsec`-signed XML, with no live IdP, no HTTP, no
  database. Unsigned, tampered-after-signing, untrusted-certificate,
  expired, wrong-audience, wrong-`InResponseTo`, and **two** distinct
  signature-wrapping shapes.
- `test_claim_mapping.py` (8 tests) — pure, no database.
- `test_federation_login_flow.py` (10 tests) — end to end through
  `FederationService` against this platform's own real dev database: JIT
  provisioning, the credential rule (structural + behavioral), session
  issuance reuse, per-org scoping, CSRF/state expiry, claim-to-RBAC-role
  mapping. Only the IdP's own HTTP endpoints (JWKS fetch, token exchange)
  are monkeypatched — no live IdP is reachable in this environment, the
  same coverage boundary every prior sub-phase's external-network calls
  used.
- `test_federation_config_crud.py` (13 tests) — the admin API, against
  real HTTP requests through the real app: permission gating, cross-org
  isolation, Entra ID/Okta/generic-OIDC/generic-SAML all configurable,
  the client secret never returned by the API and encrypted at rest,
  local login unaffected.

82 tests total. Every pre-existing test — including the entire
pre-2.3.1 local-authentication suite — passes unmodified.
