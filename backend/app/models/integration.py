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

**Phase 2.1.2 addendum** (SRS ACT-INT-FR-020..028): ``ConnectorCredential``
and ``ConnectorOAuthToken`` below extend this domain with per-instance
encrypted authentication material, reusing
``app/runtime/providers/credential_crypto.py`` directly — the same
encryption utility Phase 5.7a.5 (model-provider credentials) and Phase
5.6a.1 (``ToolCredential``) already reuse, not a new encrypted-secret
store. Neither table stores a structured plaintext credential field —
each ``encrypted_secret``/``encrypted_access_token``/
``encrypted_refresh_token`` column is a single Fernet ciphertext over a
JSON-serialized bundle (or bare token string), decrypted only inline at
the point of use, never assigned back onto a persisted row.

**Phase 2.1.3 addendum** (SRS ACT-INT-FR-040..047): ``ConnectorInstance``
gains a two-column health cache (``last_health_check_at``/
``current_health``); ``ConnectorHealthCheck`` below is the append-only,
bounded-retention history those two columns are derived from.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    # Phase 2.1.3 (ACT-INT-FR-045) -- a fast-read cache of the most recent
    # health check, so listing many instances never requires scanning
    # connector_health_checks. The history table below is the record of
    # truth; these two columns are derived, always overwritten together.
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_health: Mapped[str | None] = mapped_column(String(16), nullable=True)


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


class ConnectorCredential(Base, UUIDPrimaryKeyMixin):
    """Phase 2.1.2 SRS ACT-INT-FR-020..023, FR-025..028 — a per-instance,
    per-scheme authentication credential, encrypted at rest.

    ``encrypted_secret`` holds a single Fernet ciphertext over a
    JSON-serialized bundle of whatever fields the scheme declares it
    needs (``AuthScheme.required_fields()``) — an API key, a
    username/password pair, an OAuth2 client id/secret/token URL, or an
    mTLS cert/key pair. Never structured plaintext columns per field
    (``ACT-INT-FR-025`` — nothing here can accidentally log or serialize
    a plaintext credential because nothing here ever holds one outside
    ``ConnectorCredentialService``'s own decrypt call). ``organization_id``
    is denormalized from the parent instance for the same reason
    ``ProviderCredential``/``ToolCredential`` scope by organization
    directly — every query filters by it, never trusting the instance
    FK alone to enforce tenant isolation.

    Unique on ``(connector_instance_id, auth_scheme)`` — an instance may
    hold stored credentials for more than one scheme (e.g. mid-rotation
    to a different auth method), but exactly one is ever the *active*
    scheme actually applied, per the connector type's declared
    ``auth_requirements``."""

    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint("connector_instance_id", "auth_scheme", name="uq_connector_credentials_instance_scheme"),
    )

    connector_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    auth_scheme: Mapped[str] = mapped_column(String(48), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )


class ConnectorOAuthToken(Base, UUIDPrimaryKeyMixin):
    """Phase 2.1.2 SRS ACT-INT-FR-024 — a cached OAuth2 token pair for one
    connector instance. A token is a credential exactly like any other
    (``ACT-INT-FR-025``): both ``encrypted_access_token`` and
    ``encrypted_refresh_token`` are independent Fernet ciphertexts (never
    a shared bundle with the scheme's stored client id/secret in
    ``ConnectorCredential`` — a token's lifecycle, refreshed on its own
    schedule, is a distinct concern from the long-lived client
    credentials used to obtain it).

    Unique on ``connector_instance_id`` — one cached token pair per
    instance, refreshed in place. ``app/integration/auth/token_manager.py``
    is the only code that ever reads or writes this table, and does so
    under a row lock on the *parent* ``connector_instances`` row (not
    this one — see that module's docstring for why) so two concurrent
    invocations needing a refresh can never race into a double refresh."""

    __tablename__ = "connector_oauth_tokens"
    __table_args__ = (
        UniqueConstraint("connector_instance_id", name="uq_connector_oauth_tokens_instance"),
    )

    connector_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class ConnectorHealthCheck(Base, UUIDPrimaryKeyMixin):
    """Phase 2.1.3 SRS ACT-INT-FR-042, FR-045, FR-047 — the append-only
    history of every health check run against a connector instance
    (on-demand or the interim scheduler's own sweep).

    ``reason`` is asserted, everywhere this row is produced, to never
    carry credential or token material (``ACT-INT-FR-047``) — it is
    either ``None`` (healthy), a structural message from
    ``ConnectorCredentialService.validate()`` (already safe by 2.1.2's
    own design), or a truncated exception message from a connector's own
    ``health_check()`` (never from the auth-resolution path, which never
    reaches a connector's code at all — see ``app/integration/health.py``).

    **Bounded retention**: `ConnectorHealthService` caps history at
    ``_HEALTH_HISTORY_RETENTION`` rows per instance (newest kept), a
    simple cap-at-N rollup rather than a time-based one — see that
    module's docstring for the reasoning and where to revisit it if
    volume ever grows enough to matter."""

    __tablename__ = "connector_health_checks"

    connector_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    check_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    auth_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True,
    )
