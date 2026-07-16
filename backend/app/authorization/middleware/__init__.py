"""Enterprise authorization middleware (Phase 4.3.6).

One enforcement layer for every protected operation: the ``AuthorizationGateway``
coordinates authentication context, session state, organization resolution,
RBAC, resource authorization, ABAC, obligations, auditing, caching and metrics
in a deterministic pipeline (§4, §9). No controller, worker, agent runtime or
integration calls RBAC/ABAC directly — they call the gateway (§22).
"""

from app.authorization.middleware.context import (
    AuthorizationContext,
    AuthorizationContextBuilder,
)
from app.authorization.middleware.gateway import AuthorizationGateway, GatewayDecision
from app.authorization.middleware.pipeline import AuthorizationPipeline

__all__ = [
    "AuthorizationContext",
    "AuthorizationContextBuilder",
    "AuthorizationGateway",
    "AuthorizationPipeline",
    "GatewayDecision",
]
