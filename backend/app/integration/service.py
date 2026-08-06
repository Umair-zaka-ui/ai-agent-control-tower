"""Phase 2.1.1 SRS ACT-INT-FR-001..010 — ``ConnectorService``.

Follows the runtime domain's established pattern (``__init__(self, db:
Session)``, direct ORM queries, no repository layer — REPO_STATE §7,
§10.10): every prior sub-phase in this codebase queries its own tables
directly from its service class, and this sub-phase's own build prompt
explicitly asks for the same.

Two things worth stating up front, since they are the design decisions
this sub-phase had to make that its own build prompt did not fully
specify (see the module docstring of ``lifecycle.py`` for the third):

1. **Type resolution.** ``_CONNECTOR_TYPES`` below is a small, private,
   in-process mapping from a connector-type identifier to its Python
   implementation (``"MOCK" -> MockConnector``; Phase 2.1.2 added
   ``"MOCK_AUTH" -> MockAuthenticatedConnector`` to exercise the new
   authentication framework). This is
   *not* the connector registry ``ACT-INT-FR-040``/``FR-041`` describes —
   that is Phase 2.1.3's job (dynamic registration, health, a public
   resolution API). It exists only so this service can turn a
   ``connectors`` database row back into a live ``Connector`` instance
   when it needs to call ``validate_configuration()`` on it. A future
   2.1.3 registry supersedes this dict entirely; nothing here is meant
   to survive that sub-phase unchanged.

2. **Audit routing.** Every lifecycle transition writes an append-only
   ``connector_lifecycle_events`` row (``ACT-INT-FR-010`` names this
   table explicitly) *and* calls ``AuthorizationAuditService.record_change``
   — the same general-purpose platform audit trail every other domain in
   this codebase writes through (see ``app/authorization/services.py``).
   The two supplement, not replace, each other: the table is the
   connector-specific, queryable history a future UI reads directly
   (``GET /connectors/{id}/events``); the audit service call keeps this
   domain consistent with the platform-wide "every state change is
   audited" convention every other RUNTIME_*/ROLE_*/etc. event already
   follows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.integration.base import Connector as ConnectorImplementation
from app.integration.errors import (
    ConnectorInvalidTransitionError,
    ConnectorNotFoundError,
    ConnectorTypeNotFoundError,
)
from app.integration.lifecycle import target_state
from app.integration.connectors.database.connector import DatabaseConnector
from app.integration.connectors.rest.connector import RestConnector
from app.integration.connectors.storage.connector import StorageConnector
from app.integration.mock import MockConnector
from app.integration.mock_authenticated import MockAuthenticatedConnector
from app.integration.sdk.example.webhook_connector import WebhookConnector
from app.integration.validation import validate_declaration_complete
from app.models.integration import Connector, ConnectorInstance, ConnectorLifecycleEvent
from app.models.user import User

_CONNECTOR_TYPES: dict[str, type[ConnectorImplementation]] = {
    "MOCK": MockConnector,
    # Phase 2.1.2 -- declares a real auth_requirements.scheme so the new
    # authentication framework has something to resolve against besides
    # "NONE". Added alongside MockConnector, not in place of it (2.1.1's
    # tests assert MockConnector's own auth_requirements unchanged).
    "MOCK_AUTH": MockAuthenticatedConnector,
    # Phase 2.1.4 -- the SDK's own worked example, registered through this
    # exact same dict/`ensure_seeded` path as MOCK/MOCK_AUTH. This *is* the
    # registration-parity proof (ACT-INT-FR-062): there is no separate
    # "SDK-authored connector" registration mechanism to demonstrate --
    # WebhookConnector goes through the identical code first-party
    # connectors always have.
    "SDK_EXAMPLE_WEBHOOK": WebhookConnector,
    # Phase 2.2.1 -- the first real, generic connector; registers through
    # this exact same dict/`ensure_seeded` path as every connector before
    # it (registration parity, ACT-INT-FR-062's guarantee extending to
    # real connectors too, not only SDK examples).
    "REST": RestConnector,
    # Phase 2.2.2 -- the second real, generic connector; same registration
    # path, no branching.
    "DATABASE": DatabaseConnector,
    # Phase 2.2.3 -- the third real, generic connector; same registration
    # path, no branching.
    "STORAGE": StorageConnector,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorTypeService:
    """Read/registration side of connector *types* (``connectors`` table).

    ``ensure_seeded`` is idempotent — it inserts a ``connectors`` row for
    every entry in ``_CONNECTOR_TYPES`` that isn't already present
    (matched on ``connector_type`` + the implementation's own declared
    ``version``), and never touches a row that already exists, so an
    existing instance's binding to a specific contract version is never
    disturbed by a later app restart (``ACT-INT-FR-008``)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def register(self, implementation: ConnectorImplementation) -> Connector:
        """Phase 2.1.4, ``ACT-INT-FR-062``/``FR-064`` -- the single
        registration path. ``ensure_seeded`` below calls this once per
        ``_CONNECTOR_TYPES`` entry (first-party and SDK-authored alike,
        indistinguishably); an SDK author's own test/registration code may
        also call it directly with a fresh implementation instance that
        was never added to that dict at all. There is no second,
        privileged, or more lenient path either way.

        Validates completeness first (``validate_declaration_complete`` --
        raises ``ConnectorDeclarationIncompleteError`` naming everything
        missing) *before* anything is written, then upserts by
        ``(connector_type, version)`` exactly as the previous inline
        seeding loop did -- idempotent, never edits an existing row in
        place (``ACT-INT-FR-008``)."""
        validate_declaration_complete(implementation)
        descriptor = implementation.describe()
        existing = self.db.execute(
            select(Connector).where(
                Connector.connector_type == descriptor.connector_type,
                Connector.version == descriptor.version,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = Connector(
            connector_type=descriptor.connector_type,
            version=descriptor.version,
            capabilities=dict(descriptor.capabilities),
            config_schema=dict(descriptor.config_schema),
            auth_requirements=dict(descriptor.auth_requirements),
            tool_contracts=[
                {"name": tc.name, "description": tc.description, "parameters": dict(tc.parameters)}
                for tc in descriptor.tool_contracts
            ],
        )
        self.db.add(row)
        self.db.flush()
        return row

    def ensure_seeded(self) -> None:
        for impl_cls in _CONNECTOR_TYPES.values():
            self.register(impl_cls())
        self.db.flush()

    def list_types(self) -> list[Connector]:
        self.ensure_seeded()
        return list(self.db.execute(select(Connector).order_by(Connector.connector_type, Connector.version)).scalars())

    def get_or_404(self, connector_type: str, version: str | None = None) -> Connector:
        """Resolves a type row by identifier, optionally pinned to an
        exact ``version``. With no ``version``, resolves to the most
        recently registered row for that identifier — since
        ``_CONNECTOR_TYPES`` only ever grows one row per restart (never
        edits one in place), "most recent" and "current" coincide for
        every type registered so far."""
        self.ensure_seeded()
        query = select(Connector).where(Connector.connector_type == connector_type.upper())
        if version:
            query = query.where(Connector.version == version)
        row = self.db.execute(query.order_by(Connector.created_at.desc())).scalars().first()
        if row is None:
            raise ConnectorTypeNotFoundError(connector_type)
        return row

    def implementation_for(self, row: Connector) -> ConnectorImplementation:
        impl_cls = _CONNECTOR_TYPES.get(row.connector_type)
        if impl_cls is None:
            # A type row exists (e.g. seeded by a previous app version that
            # registered a since-removed implementation) but this process
            # has no Python class for it -- treat identically to "not
            # found" rather than crash; nothing in this sub-phase can
            # remove a _CONNECTOR_TYPES entry at runtime, so this path is
            # unreachable today but is a real, deliberate fail-closed
            # guard for whenever 2.1.3's dynamic registry replaces this dict.
            raise ConnectorTypeNotFoundError(row.connector_type)
        return impl_cls()


class ConnectorService:
    """Tenant instance CRUD + lifecycle (``connector_instances`` /
    ``connector_lifecycle_events``)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.types = ConnectorTypeService(db)

    # --- lookups ----------------------------------------------------- #
    def get_or_404(self, organization_id: uuid.UUID, instance_id: uuid.UUID) -> ConnectorInstance:
        row = self.db.execute(
            select(ConnectorInstance).where(
                ConnectorInstance.id == instance_id,
                ConnectorInstance.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise ConnectorNotFoundError(instance_id)
        return row

    def list_for_org(self, organization_id: uuid.UUID) -> list[ConnectorInstance]:
        return list(self.db.execute(
            select(ConnectorInstance).where(ConnectorInstance.organization_id == organization_id)
            .order_by(ConnectorInstance.created_at.desc())
        ).scalars())

    def list_events(self, organization_id: uuid.UUID, instance_id: uuid.UUID) -> list[ConnectorLifecycleEvent]:
        self.get_or_404(organization_id, instance_id)  # tenant-scope check (AC-08)
        return list(self.db.execute(
            select(ConnectorLifecycleEvent)
            .where(ConnectorLifecycleEvent.connector_instance_id == instance_id)
            .order_by(ConnectorLifecycleEvent.created_at)
        ).scalars())

    # --- creation ------------------------------------------------------ #
    def create_instance(
        self, actor: User, organization_id: uuid.UUID, *, connector_type: str, name: str,
        version: str | None = None, configuration: Mapping[str, Any] | None = None,
    ) -> ConnectorInstance:
        """Creates a ``registered`` instance (``ACT-INT-FR-004``). If a
        non-empty ``configuration`` is supplied up front, immediately
        validates and advances it to ``configured`` in the same call —
        pure convenience so a caller with valid configuration in hand
        doesn't need a second round trip; a caller with none yet, or with
        invalid configuration (AC-11 — stays ``registered``, structured
        error surfaced, nothing committed), is unaffected."""
        type_row = self.types.get_or_404(connector_type, version)
        instance = ConnectorInstance(
            organization_id=organization_id, connector_id=type_row.id, name=name,
            configuration={}, lifecycle_state="registered", created_by=actor.id,
        )
        self.db.add(instance)
        self.db.flush()
        if configuration:
            self._configure(actor, instance, type_row, configuration)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    # --- configuration / the "configure" transition -------------------- #
    def update_configuration(
        self, actor: User, organization_id: uuid.UUID, instance_id: uuid.UUID,
        configuration: Mapping[str, Any],
    ) -> ConnectorInstance:
        """The only way to set or change an instance's ``configuration``
        after creation (``PATCH /connectors/{id}``, ``ACT-INT-FR-005``).

        Allowed from ``registered``, ``configured`` or ``disabled`` —
        **not** ``active``: an operator must ``disable`` first. This
        mirrors this codebase's existing taste for "you cannot silently
        rewrite something live" (e.g. a published ``AgentVersion``'s
        configuration is frozen) and gives a single, unambiguous moment
        (disable) where a live connector's configuration is known to be
        settled — a genuine judgment call the build prompt's §7 endpoint
        list left unstated, documented here and in REPO_STATE.

        From ``registered``/``disabled`` this also performs the
        ``configure`` lifecycle transition (landing in ``configured``,
        writing a lifecycle event); from ``configured`` it is an in-place
        update with no state change (and therefore no lifecycle event —
        only actual transitions are recorded, matching AC-13's "each
        transition writes a row," not "every write")."""
        instance = self.get_or_404(organization_id, instance_id)
        if instance.lifecycle_state == "active":
            raise ConnectorInvalidTransitionError(instance.lifecycle_state, "configure")
        type_row = self.db.get(Connector, instance.connector_id)
        self._configure(actor, instance, type_row, configuration)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def _configure(
        self, actor: User, instance: ConnectorInstance, type_row: Connector, configuration: Mapping[str, Any],
    ) -> None:
        """Shared by ``create_instance`` and ``update_configuration``:
        validate, store, and — only when the current state is
        ``registered`` or ``disabled`` — advance to ``configured``.
        Never commits; callers own the transaction boundary."""
        implementation = self.types.implementation_for(type_row)
        implementation.validate_configuration(configuration)  # raises ConnectorConfigInvalidError, uncommitted (AC-11)
        instance.configuration = dict(configuration)
        if instance.lifecycle_state in ("registered", "disabled"):
            self._transition(actor, instance, event="configure", reason=None)

    # --- activate / disable / mark_failed ------------------------------ #
    def activate(self, actor: User, organization_id: uuid.UUID, instance_id: uuid.UUID) -> ConnectorInstance:
        instance = self.get_or_404(organization_id, instance_id)
        self._transition(actor, instance, event="activate", reason=None)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def disable(
        self, actor: User, organization_id: uuid.UUID, instance_id: uuid.UUID, *, reason: str | None = None,
    ) -> ConnectorInstance:
        instance = self.get_or_404(organization_id, instance_id)
        self._transition(actor, instance, event="disable", reason=reason)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def mark_failed(
        self, actor: User | None, organization_id: uuid.UUID, instance_id: uuid.UUID, *, reason: str,
    ) -> ConnectorInstance:
        """Still not exposed over HTTP directly (no dedicated route in
        either the 2.1.1 or 2.1.3 build prompt's §7) — as of Phase 2.1.3
        this is driven automatically by ``ConnectorHealthService`` on a
        failing health check (``ACT-INT-FR-044``), and remains a real,
        directly callable/testable service method for manual/test use."""
        instance = self.get_or_404(organization_id, instance_id)
        self._transition(actor, instance, event="mark_failed", reason=reason)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def recover(
        self, actor: User | None, organization_id: uuid.UUID, instance_id: uuid.UUID,
    ) -> ConnectorInstance:
        """Phase 2.1.3, ``ACT-INT-FR-044`` — the ``failed -> active``
        counterpart to ``mark_failed``, driven by
        ``ConnectorHealthService`` on a subsequent passing health check.
        No reason is recorded (mirrors ``activate``'s own signature) —
        the fact that it recovered, and the health check that proved it,
        is the record; ``state_reason`` is cleared to ``None`` since the
        prior failure reason no longer describes the instance's current
        state."""
        instance = self.get_or_404(organization_id, instance_id)
        self._transition(actor, instance, event="recover", reason=None)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    # --- the one place every transition happens ------------------------ #
    def _transition(
        self, actor: User | None, instance: ConnectorInstance, *, event: str, reason: str | None,
    ) -> None:
        from_state = instance.lifecycle_state
        to_state = target_state(event, from_state)
        if to_state is None:
            raise ConnectorInvalidTransitionError(from_state, event)
        instance.lifecycle_state = to_state
        instance.state_reason = reason
        instance.updated_at = _now()
        self.db.add(ConnectorLifecycleEvent(
            connector_instance_id=instance.id, from_state=from_state, to_state=to_state,
            reason=reason, actor_id=actor.id if actor else None,
        ))
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.INTEGRATION_CONNECTOR_STATE_CHANGED,
            organization_id=instance.organization_id, actor_id=actor.id if actor else None,
            # Phase 2.1.3, ACT-INT-FR-046 -- a transition *into* `failed`
            # is the alert-worthy moment (see app/integration/health.py's
            # docstring for why this event, not a dedicated one, is what
            # this codebase uses as its alerting signal). `severity`
            # mirrors the same field RUNTIME_TOOL_EGRESS_DENIED already
            # carries in its own meta for the identical reason.
            meta={"connector_instance_id": str(instance.id), "event": event,
                  "from_state": from_state, "to_state": to_state, "reason": reason,
                  "severity": "CRITICAL" if to_state == "failed" else "INFO"},
        )
        self.db.flush()
