"""Phase 2.3.1 SRS ACT-INT-FR-180..187 — external identity federation.

**The inversion.** Every connector sub-phase in Milestone 2 (2.1.2, 2.2.x)
authenticated the *platform to* an external system — the platform holds a
secret and presents it outward. This package runs the opposite direction:
an enterprise's own IdP authenticates a *user to the platform*. The
platform verifies a signed assertion and trusts it; it never sees, and
never stores, the user's own credential (``ACT-INT-FR-186``) — that stays
entirely with the IdP. Where a connector's whole value is holding a
secret *safely*, federation's whole value is holding no secret at all.

Four modules:

- ``oidc.py`` — the OIDC authorization-code flow. Its security core,
  ``verify_id_token``, is pure (no HTTP, no database) and exhaustively
  testable against every bypass vector with no live IdP required.
- ``saml.py`` — SAML 2.0 web-browser SSO. A thin wrapper around
  ``python3-saml``/``xmlsec`` — XML signature verification is never hand-
  rolled (see that module's own docstring for why).
- ``claim_mapping.py`` — pure IdP-group-claim → platform-role-name
  mapping (``ACT-INT-FR-183``), configuration, not code.
- ``service.py`` — ``FederationService``: per-organization configuration,
  login orchestration for both protocols, JIT provisioning
  (``ACT-INT-FR-184``) via the existing ``UserProvisioningService`` seam,
  and session issuance through the platform's **existing** session
  pipeline — never a parallel one (``ACT-INT-FR-182``)."""
