"""Session, refresh-token and device models (SRS 4.2.2.2 §6, §7, §13).

A session — not a JWT — is the source of truth for whether a caller may act. The
JWT is disposable; ``auth_sessions`` decides.

Three tables:

- ``auth_sessions``  the logical session: identity + device + timing + security
- ``refresh_tokens`` a rotating token belonging to exactly one token *family*
- ``auth_devices``   a recognised device, with a trust posture
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import DeviceStatus, SessionStatus
from app.models.mixins import UUIDPrimaryKeyMixin


class UserSession(Base, UUIDPrimaryKeyMixin):
    """An authenticated human session (table ``auth_sessions``, SRS §6).

    Timing invariants:

    - ``idle_expires_at``     = last_activity_at + SESSION_IDLE_TIMEOUT
    - ``absolute_expires_at`` = created_at + SESSION_ABSOLUTE_TIMEOUT (or
      SESSION_REMEMBER_ME when the login asked to be remembered)

    A session is usable only while ``status`` can authenticate **and** now is
    before both deadlines. ``status`` is the recorded fact; the deadlines are the
    derived fact. ``SessionLifecycleService.assert_usable`` reconciles them.
    """

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionStatus.ACTIVE.value, index=True
    )

    # --- device / client (SRS §6) ------------------------------------- #
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    browser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # --- location (SRS §6) --------------------------------------------- #
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    login_method: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- timing (SRS §12) ---------------------------------------------- #
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- revocation (SRS §20) ------------------------------------------ #
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- security (SRS §15) -------------------------------------------- #
    security_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- refresh token family (SRS §7) --------------------------------- #
    # One session owns exactly one family. Reuse of any token in the family kills
    # the family *and* the session.
    refresh_token_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )


class RefreshToken(Base, UUIDPrimaryKeyMixin):
    """A rotating refresh token in a session's family (table ``refresh_tokens``).

    Only the hash is persisted; the plaintext ``rt_…`` is returned once. Rotation
    revokes the old token and links it to its successor (``rotated_to_id``),
    forming an audit chain. Presenting a token that is *revoked and already
    rotated* is a replay: see ``RefreshRotationService.is_reuse``.
    """

    __tablename__ = "refresh_tokens"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # First-class token family (SRS §7). Denormalised from the session so a reuse
    # sweep never needs to join, and so families outlive a deleted session row.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_to_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Set on the exact token that was replayed — the forensic anchor for §9.
    reuse_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserDevice(Base, UUIDPrimaryKeyMixin):
    """A device a user has authenticated from (table ``auth_devices``, SRS §13).

    Identified by a fingerprint derived from stable request characteristics. The
    fingerprint is *advisory*: it is derived from client-supplied headers and can
    be forged, so it is used to recognise a device for UX and risk scoring — never
    as an authentication factor on its own.
    """

    __tablename__ = "auth_devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    browser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operating_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DeviceStatus.UNKNOWN.value, index=True
    )
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def trusted(self) -> bool:
        return self.status == DeviceStatus.TRUSTED.value

    @property
    def blocked(self) -> bool:
        return self.status == DeviceStatus.BLOCKED.value
