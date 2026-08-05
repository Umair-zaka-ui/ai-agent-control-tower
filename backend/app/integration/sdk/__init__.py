"""Phase 2.1.4 SRS ACT-INT-FR-060..066 — the connector authoring surface.

**Importing from ``app.integration.sdk`` is the supported contract.**
Importing from any other ``app.integration.*`` (or ``app.runtime.*``)
module directly is not a connector author's job and is not supported —
those are platform internals that may change without notice. This module
re-exports, by name, exactly what an author needs and nothing else; what
is *not* re-exported here is deliberately withheld, not merely omitted.

**What is withheld, and why (the containment core, `ACT-INT-FR-066`)**:

- No database session, ``ConnectorService``/``ConnectorRegistry``/
  ``ConnectorCredentialService``, or any other service class. A connector's
  own code (``describe``, ``validate_configuration``, ``health_check``)
  never receives a session, an organization id, or any object that could
  reach another tenant's data — the ABC's own method signatures are
  structurally incapable of it, not merely convention.
- No ``AuthScheme``/``OutboundRequest``/credential-resolution machinery,
  and no way to register a new authentication scheme. An author *declares*
  a scheme identifier (``auth_requirements={"scheme": "BEARER"}``,
  validated against ``SUPPORTED_AUTH_SCHEMES``) — they never see, handle,
  or apply a decrypted credential. That happens entirely outside a
  connector's own code, in ``app.integration.auth``, which this surface
  does not expose.
- No ``httpx``/``requests``/raw socket access, and no re-export of
  ``app.runtime.tools.egress_guard``/``http_executor`` directly.
  ``GovernedHttpClient`` (``app.integration.sdk.http``) is the *only*
  network primitive on this surface — every outbound call it makes is
  policy-checked against the host(s) the client was built with, before any
  DNS lookup or socket is opened. There is no affordance here to make an
  undeclared outbound call; the SDK simply does not offer one.
- No audit-suppression hook of any kind — ``AuthorizationAuditService`` is
  not exported, and nothing on this surface accepts a "skip audit" flag.
- No route-registration mechanism. A connector's actions reach the
  platform exclusively through the existing, permission-gated
  ``app/integration/routes.py`` surface (every route requires a permission
  via ``AuthorizationGateway``) — the SDK offers no way to add a second,
  ungated entry point.

**Scope — trusted authors, not an adversarial marketplace.** This surface
is designed for first-party and trusted-enterprise developers (a
customer's own integration engineers, authoring a connector they deploy in
their own tenant) who write connectors in good faith against a contract
that makes the dangerous mistakes structurally unavailable. It is *not* a
sandbox for running arbitrary, actively adversarial third-party code —
that containment problem (a malicious connector attempting to escape or
exfiltrate) belongs to Milestone 12's marketplace, which builds on the
guarantees here but must additionally assume hostile intent. Do not treat
"the SDK offers no dangerous affordance" as "this SDK makes arbitrary code
safe to execute" — those are different guarantees."""

from __future__ import annotations

from app.integration.base import Connector, validate_configuration_schema
from app.integration.errors import ConnectorConfigInvalidError
from app.integration.sdk.http import GovernedHttpClient
from app.integration.sdk.testing import ConnectorTestHarness, HealthCheckOutcome
from app.integration.types import ConnectorDescriptor, ConnectorLifecycleState, ToolContract


def _supported_auth_schemes() -> frozenset[str]:
    """A snapshot of every registered authentication scheme identifier, for
    an author to validate ``auth_requirements["scheme"]`` against —
    ``"NONE"`` (no authentication) is always valid too, alongside whatever
    ``app.integration.auth.registry`` has registered (six today). Computed
    lazily, not at import time, so this module never has to import the
    auth package eagerly just to build one constant."""
    from app.integration.auth import registry as _auth_registry

    return frozenset({"NONE", *_auth_registry.registered_identifiers()})


SUPPORTED_AUTH_SCHEMES: frozenset[str] = _supported_auth_schemes()

__all__ = [
    # The connector contract to subclass.
    "Connector",
    # Declaration types.
    "ConnectorDescriptor",
    "ToolContract",
    "ConnectorLifecycleState",
    "SUPPORTED_AUTH_SCHEMES",
    # Configuration validation.
    "validate_configuration_schema",
    "ConnectorConfigInvalidError",
    # The one governed network primitive.
    "GovernedHttpClient",
    # Testing utilities (ACT-INT-FR-063).
    "ConnectorTestHarness",
    "HealthCheckOutcome",
]
