"""Enterprise Integration Framework models (Phase 2.1.1 SRS ACT-INT-FR-001..010).

Two-table split mirrors the ``ModelProvider``/registered-instance shape this
sub-phase deliberately follows (see ``app/integration/base.py``'s module
docstring): ``Connector`` is a **type** — a registered implementation and its
declared contract, platform-wide, versioned; ``ConnectorInstance`` is a
tenant's configured **use** of one type, carrying its own configuration and
lifecycle state. Many instances of one type coexist across many
organizations (``ACT-INT-FR-004``, ``ACT-INT-FR-007``).

``ConnectorLifecycleEvent`` is the append-only audit trail of every instance
state transition (``ACT-INT-FR-010``) — append-only by convention, the same
way every other audit-shaped table in this codebase is (no DB-level REVOKE
anywhere in this schema; see ``ConnectorService``, which never exposes an
update/delete path for this table).

No credential, authentication, health-check or tool-execution concept
appears here — those are 2.1.2/2.1.3/the tool bridge, deliberately out of
scope for this sub-phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class Connector(Base, UUIDPrimaryKeyMixin):
    """A registered connector **type** — the implementation and its
    declared contract (``ACT-INT-FR-001``, ``FR-002``), analogous to a
    registered ``ModelProvider`` class. Platform-wide, not tenant-scoped —
    the same "global catalog" shape release channels and signing keys
    already use elsewhere in this codebase.

    Unique on ``(connector_type, version)`` (``ACT-INT-FR-008``) — a new
    version is a new row, never an in-place edit of an existing one, so an
    already-bound ``ConnectorInstance`` keeps referencing exactly the
    contract it was configured against."""

    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("connector_type", "version", name="uq_connectors_type_version"),
    )

    connector_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    auth_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tool_contracts: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class ConnectorInstance(Base, UUIDPrimaryKeyMixin):
    """A tenant's configured use of one connector type (``ACT-INT-FR-004``).

    ``configuration`` is validated against its type's ``config_schema``
    before the ``registered -> configured`` transition
    (``ACT-INT-FR-005``); **no credential ever lives on this row** — that is
    2.1.2's concern, referenced (once it exists) rather than stored here.
    ``lifecycle_state`` is a plain string column, not a DB enum, matching
    this codebase's established convention for lifecycle-state columns
    (e.g. ``AgentVersion.status``, ``ConnectorInstance``'s own sibling
    tables) — the single authority on valid values/transitions is
    ``app/integration/lifecycle.py``, not a database constraint."""

    __tablename__ = "connector_instances"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_connector_instances_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="registered", index=True)
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ConnectorLifecycleEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only audit trail of every ``ConnectorInstance`` lifecycle
    transition (``ACT-INT-FR-010``). ``ConnectorService`` only ever
    ``db.add()``s a row here — no method to update or delete one exists,
    which is this codebase's established way of enforcing "append-only"
    (no table in this schema uses a DB-level ``REVOKE``; see
    ``AgentVersionStatusHistory``, ``AgentLifecycleEvent`` for the same
    convention)."""

    __tablename__ = "connector_lifecycle_events"

    connector_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
