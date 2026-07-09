"""Account-protection ORM models (4.2.2.3.4 §17).

Login *attempts* are not modelled here: the existing ``login_history`` table already
records every attempt (success or failure, with IP/UA/country), so Part 4.2.2.3.4
**extends** it with the risk fields rather than forking a second attempts table. See
``login_history.py`` and ``docs/security/account-protection.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

# NOTE: this model deliberately does NOT import from ``app.identity.protection`` —
# doing so would run that package's __init__ (services) while the models package is
# still initialising, a circular import. Status/reason values are plain strings here;
# the enums (``AccountLockStatus`` etc.) live in ``app.identity.protection.enums`` for
# the service layer.


class AccountLock(Base, UUIDPrimaryKeyMixin):
    """A stateful, time-bounded lock on an account (§8, §17).

    Progressive: each new lock while the account keeps failing extends the duration
    (15m → 30m → 1h → 24h → security review). The lock is the source of truth for
    "is this account locked right now", not a recomputed window.
    """

    __tablename__ = "account_locks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", index=True
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # NULL expiry = an indefinite lock (e.g. SECURITY_REVIEW): only an admin lifts it.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlocked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_account_locks_user_status", "user_id", "status"),)


class IdentityRiskEvent(Base, UUIDPrimaryKeyMixin):
    """A scored authentication attempt (§17, §26). Distinct from ``security_events``:
    it carries the structured risk fields (score, level, signals) that the risk-events
    page filters and charts on."""

    __tablename__ = "identity_risk_events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (Index("ix_identity_risk_events_org_created", "organization_id", "created_at"),)


class BlockedIp(Base, UUIDPrimaryKeyMixin):
    """An IP address denied at the door (§16). ``organization_id`` NULL = a global
    (platform-wide) block; otherwise scoped to one tenant."""

    __tablename__ = "blocked_ips"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NULL = permanent until removed; otherwise a temporary block that lapses.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_blocked_ips_org_ip", "organization_id", "ip_address"),)


class IdentityProtectionRule(Base, UUIDPrimaryKeyMixin):
    """An admin-authored rule: conditions → decision (§16, §27).

    ``conditions`` is a JSON list of ``{field, op, value}`` clauses evaluated against
    the login attempt's signals; the highest-priority *enabled* rule that matches wins.
    """

    __tablename__ = "identity_protection_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
