"""The authorization context (Phase 4.3.6 §5).

One immutable object carries everything the pipeline needs — identity, session,
organization, resource, action, environment and the accumulating decision
trace. Immutability is a security requirement (§36): once built, no later
pipeline stage (or business code holding a reference) can manipulate the
context another stage already decided on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

from sqlalchemy.orm import Session


def _frozen(mapping: dict[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True)
class AuthorizationContext:
    """§5 — the immutable per-request evaluation context.

    ``identity_kind`` is USER / AGENT / SYSTEM (§10). ``attributes`` carries
    caller-supplied dynamic context (row counts, ai.* signals …) — never
    ``identity.*`` keys, which the gateway strips for non-simulator callers.
    ``decision_trace`` is a tuple: appending requires ``with_trace`` which
    returns a *new* context, so a stage can never rewrite history.
    """

    request_id: str
    correlation_id: str
    identity_id: uuid.UUID | None
    identity_kind: str  # USER / AGENT / SYSTEM
    organization_id: uuid.UUID | None
    permission: str
    action: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    source: str = "API"  # API / WORKER / SCHEDULER / WORKFLOW / AGENT / INTEGRATION
    roles: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=lambda: _frozen(None))
    environment: Mapping[str, Any] = field(default_factory=lambda: _frozen(None))
    justification: str | None = None
    decision_trace: tuple[str, ...] = ()

    def with_trace(self, *steps: str) -> "AuthorizationContext":
        """Return a new context with ``steps`` appended to the trace."""
        return replace(self, decision_trace=self.decision_trace + steps)


class AuthorizationContextBuilder:
    """§6, §21 — the single place authorization contexts are assembled.

    Controllers never hand-build context objects; enforcement points pass the
    raw request facts here. ``identity.*`` keys are stripped from caller
    attributes so a request can never spoof its own subject (§36, 4.3.5 §40).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def build(
        self,
        *,
        identity_id: uuid.UUID | None,
        identity_kind: str,
        organization_id: uuid.UUID | None,
        permission: str,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        source: str = "API",
        roles: tuple[str, ...] = (),
        attributes: dict[str, Any] | None = None,
        environment: dict[str, Any] | None = None,
        justification: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        allow_subject_attributes: bool = False,
    ) -> AuthorizationContext:
        attrs = dict(attributes or {})
        if not allow_subject_attributes:
            attrs = {k: v for k, v in attrs.items() if not k.startswith("identity.")}
        rid = request_id or str(uuid.uuid4())
        return AuthorizationContext(
            request_id=rid,
            correlation_id=correlation_id or rid,
            identity_id=identity_id,
            identity_kind=identity_kind,
            organization_id=organization_id,
            permission=permission,
            action=action or permission,
            resource_type=resource_type,
            resource_id=resource_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            source=source,
            roles=tuple(roles),
            attributes=_frozen(attrs),
            environment=_frozen(environment),
            justification=justification,
        )
