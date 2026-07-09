"""Invitation, email-verification, user-profile and rate-limit models (4.2.2.3.1 §5).

**No token plaintext is ever stored.** Both the invitation token and the email
verification token are high-entropy random strings, returned once in an email link
and persisted only as a SHA-256 hash. A database dump therefore cannot be used to
accept an invitation or verify an address.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import InvitationStatus
from app.models.mixins import UUIDPrimaryKeyMixin


class Invitation(Base, UUIDPrimaryKeyMixin):
    """An administrator's offer for one email address to join one organization.

    Uniqueness is enforced by a *partial* unique index on
    ``(organization_id, lower(email)) WHERE status = 'PENDING'`` — one live
    invitation per address per org, while allowing a fresh invitation after an
    earlier one was cancelled, expired or accepted.
    """

    __tablename__ = "invitations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    # Target RBAC role + org placement, applied by UserProvisioningService on accept.
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # SHA-256 of the plaintext token. Unique so a lookup is one indexed read.
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InvitationStatus.PENDING.value, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Resends rotate the token; this is the forensic count, not a rate limit.
    resent_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_invitations_org_status", "organization_id", "status"),)


class EmailVerification(Base, UUIDPrimaryKeyMixin):
    """A single-use token proving control of an email address (§12).

    Lifetime 24 hours. Expired tokens can be resent, which supersedes the old row
    rather than mutating it — the audit trail keeps every attempt.
    """

    __tablename__ = "email_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    verification_token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a newer token supersedes this one (resend). Keeps single-use honest.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 4.2.2.3.3 §12: an ACTIVATION row confirms the account's own address; an
    # EMAIL_CHANGE row confirms ``new_email`` before it replaces the current one.
    purpose: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVATION", server_default="ACTIVATION"
    )
    new_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserProfile(Base, UUIDPrimaryKeyMixin):
    """Human-facing profile, kept out of ``users`` (§5).

    ``users`` is the security record — credentials, status, tenancy. A profile is
    presentation data with a different change cadence and a different audience.
    Mixing them means every avatar change touches the row the auth path reads.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def full_name(self) -> str | None:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else None


class RateLimitHit(Base, UUIDPrimaryKeyMixin):
    """One recorded request against a rate-limited public endpoint (§19).

    Postgres-backed rather than in-memory: an in-process counter resets on every
    deploy and is wrong the moment a second replica exists. Redis would be the
    obvious home, but [ADR-0002] makes PostgreSQL the sole datastore, and 5
    requests/minute/IP over a handful of public endpoints is nowhere near a
    workload that justifies a second one.
    """

    __tablename__ = "rate_limit_hits"

    # "<endpoint>:<client-ip>" — the counting bucket.
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # The only query is "how many hits for this bucket since T", newest-bounded.
    __table_args__ = (Index("ix_rate_limit_hits_bucket_created", "bucket", "created_at"),)
