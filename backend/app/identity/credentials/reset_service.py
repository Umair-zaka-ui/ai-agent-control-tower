"""PasswordResetService — administrative reset & temporary passwords (SRS §12, §16).

An administrator can *reset* a user's password (issuing a one-time temporary
password that must be changed at first login) but can never *see* an existing
password. The temporary password is returned to the caller exactly once — to be
handed over or emailed — and is stored only as an argon2id hash like any other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.credentials.audit import CredentialAuditService, CredentialContext
from app.identity.credentials.service import (
    CredentialService,
    SessionRevoker,
    generate_temporary_password,
    _no_revoke,
)
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TemporaryCredential:
    """The result of an admin reset. ``password`` is plaintext, shown once."""

    user: User
    password: str
    expires_at: datetime


class PasswordResetService:
    def __init__(self, db: Session, *, revoke_sessions: SessionRevoker | None = None) -> None:
        self.db = db
        self.credentials = CredentialService(db, revoke_sessions=revoke_sessions)
        self.audit = CredentialAuditService(db)
        self._revoke_sessions = revoke_sessions or _no_revoke

    def admin_reset(
        self,
        user: User,
        *,
        actor: User,
        context: CredentialContext | None = None,
        temporary_password: str | None = None,
    ) -> TemporaryCredential:
        """Reset ``user``'s password to a temporary one that must be changed at
        first login (SRS §12, §16).

        - The temp password expires in ``TEMP_PASSWORD_TTL_HOURS`` (§12) and sets
          ``must_change_password`` so the next login is forced through the change
          flow before any feature is reachable (§11, §13).
        - Every live session for the user is revoked: a reset exists precisely for
          the case where the account may be compromised, so leaving the attacker's
          session alive would defeat it (§16).
        """
        temp = temporary_password or generate_temporary_password()
        expires_at = _now() + timedelta(hours=settings.TEMP_PASSWORD_TTL_HOURS)

        # Reuse the shared write path so the old hash still enters history and the
        # temp password is validated — but force the short expiry and the flag.
        self.credentials._apply_new_password(
            user,
            temp,
            actor=actor,
            context=context,
            event=AuthEventType.PASSWORD_RESET,
            metadata={"by_admin": True, "temporary": True},
            force_expire=expires_at,
            must_change=True,
        )
        self.audit.record(
            AuthEventType.TEMP_PASSWORD_CREATED,
            organization_id=user.organization_id,
            identity_id=user.id,
            actor_id=actor.id,
            context=context,
            metadata={"expires_at": expires_at.isoformat()},
        )

        # Kill every session: the person resetting is not necessarily the owner.
        self._revoke_sessions(user.id, "PASSWORD_RESET")

        self.db.commit()
        return TemporaryCredential(user=user, password=temp, expires_at=expires_at)
