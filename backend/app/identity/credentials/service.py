"""CredentialService — the one place a human password is set or changed (SRS §9, §14, §15).

Every write of ``users.password_hash`` for a human should go through here so the
full discipline is applied exactly once: verify the current password, enforce
minimum age, validate complexity, reject reuse, hash with argon2id, record the
old hash in history, stamp the lifecycle fields, audit, and (by policy) revoke the
user's other sessions.

Session revocation is injected as a callable so this service does not import the
authentication stack (which imports models, which would cycle).
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import security as core_security
from app.identity.auth.enums import AuthEventType
from app.identity.credentials.audit import CredentialAuditService, CredentialContext
from app.identity.credentials.history_service import PasswordHistoryService
from app.identity.credentials.policy_service import PasswordPolicyService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.security import passwords as policy
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Session-revocation hook: (user_id, reason) -> revoked count. The default is a
# no-op so the service is usable without the auth stack (e.g. in unit tests); the
# API layer injects the real one.
SessionRevoker = Callable[[uuid.UUID, str], int]


def _no_revoke(_user_id: uuid.UUID, _reason: str) -> int:
    return 0


def generate_temporary_password() -> str:
    """A random password that satisfies the policy (SRS §12).

    Built from all four required classes plus length, then shuffled, so the
    generated value never trips the complexity gate it will be stored under.
    Sequences/repeats are astronomically unlikely from CSPRNG picks; the caller
    validates anyway.
    """
    specials = "!@#$%^&*-_=+?"
    picks = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(specials),
    ]
    alphabet = string.ascii_letters + string.digits + specials
    picks += [secrets.choice(alphabet) for _ in range(16 - len(picks))]
    secrets.SystemRandom().shuffle(picks)
    return "".join(picks)


class CredentialService:
    def __init__(self, db: Session, *, revoke_sessions: SessionRevoker | None = None) -> None:
        self.db = db
        self.history = PasswordHistoryService(db)
        self.policy = PasswordPolicyService()
        self.audit = CredentialAuditService(db)
        self._revoke_sessions = revoke_sessions or _no_revoke

    # ------------------------------------------------------------------ #
    # Self-service change (SRS §15)
    # ------------------------------------------------------------------ #
    def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
        actor: User | None = None,
        context: CredentialContext | None = None,
        revoke_other_sessions: bool | None = None,
    ) -> User:
        """Change a user's own password. ``actor`` defaults to ``user`` itself.

        A first-login change from a temporary password follows the same path — the
        temp password *is* the current password, so verifying it proves possession —
        but is audited as ``FIRST_LOGIN_PASSWORD_CHANGED`` and skips the min-age gate.
        """
        actor = actor or user
        is_first_login = bool(user.must_change_password)

        if not core_security.verify_password(current_password, user.password_hash):
            self.audit.record(
                AuthEventType.PASSWORD_POLICY_VIOLATION,
                organization_id=user.organization_id,
                identity_id=user.id,
                actor_id=actor.id,
                context=context,
                metadata={"reason": "invalid_current_password"},
            )
            self.db.commit()
            raise IdentityError(
                ErrorCode.INVALID_CURRENT_PASSWORD, "Your current password is incorrect."
            )

        # Minimum age: cannot change again too soon (skipped for a forced change).
        if not self.policy.min_age_ok(user):
            raise IdentityError(
                ErrorCode.PASSWORD_MIN_AGE,
                "Your password was changed too recently. Please try again later.",
            )

        self._apply_new_password(
            user,
            new_password,
            actor=actor,
            context=context,
            event=(
                AuthEventType.FIRST_LOGIN_PASSWORD_CHANGED
                if is_first_login
                else AuthEventType.PASSWORD_CHANGED
            ),
            metadata={"first_login": is_first_login},
        )

        revoke = (
            settings.PASSWORD_CHANGE_REVOKES_SESSIONS
            if revoke_other_sessions is None
            else revoke_other_sessions
        )
        if revoke:
            self._revoke_sessions(user.id, "PASSWORD_CHANGED")

        self.db.commit()
        return user

    # ------------------------------------------------------------------ #
    # Shared write path — validate, reject reuse, hash, history, stamp, audit
    # ------------------------------------------------------------------ #
    def _apply_new_password(
        self,
        user: User,
        new_password: str,
        *,
        actor: User,
        context: CredentialContext | None,
        event: AuthEventType,
        metadata: dict | None = None,
        force_expire: datetime | None = None,
        must_change: bool = False,
    ) -> None:
        # 1. Complexity (raises PasswordPolicyError -> 422 via the handler).
        try:
            self.policy.validate(new_password, user=user)
        except policy.PasswordPolicyError:
            self.audit.record(
                AuthEventType.PASSWORD_POLICY_VIOLATION,
                organization_id=user.organization_id,
                identity_id=user.id,
                actor_id=actor.id,
                context=context,
                metadata={"reason": "policy"},
            )
            self.db.commit()
            raise

        # 2. Reuse: not the current password, nor any of the last N (SRS §10).
        if self.history.is_reused(user.id, new_password, current_hash=user.password_hash):
            self.audit.record(
                AuthEventType.PASSWORD_REUSED_ATTEMPT,
                organization_id=user.organization_id,
                identity_id=user.id,
                actor_id=actor.id,
                context=context,
                metadata={"history_depth": settings.PASSWORD_HISTORY_DEPTH},
            )
            self.db.commit()
            raise IdentityError(
                ErrorCode.PASSWORD_REUSED,
                f"Choose a password you have not used in your last "
                f"{settings.PASSWORD_HISTORY_DEPTH} passwords.",
            )

        # 3. The password being replaced joins the history (unless it was a
        #    sentinel/unusable hash — SSO/SCIM identities have no real password).
        if not core_security.is_unusable_password(user.password_hash):
            self.history.record(user.id, user.password_hash)

        # 4. Hash + stamp the lifecycle fields.
        now = _now()
        user.password_hash = core_security.hash_password(new_password)
        user.password_changed_at = now
        user.password_expires_at = force_expire or self.policy.expires_at_from(now)
        user.must_change_password = must_change
        self.db.flush()

        self.audit.record(
            event,
            organization_id=user.organization_id,
            identity_id=user.id,
            actor_id=actor.id,
            context=context,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------ #
    # Recovery reset (4.2.2.3.3) — no current password, revoke everything
    # ------------------------------------------------------------------ #
    def apply_recovery_reset(
        self,
        user: User,
        new_password: str,
        *,
        actor: User | None = None,
        context: CredentialContext | None = None,
        event: AuthEventType = AuthEventType.PASSWORD_RESET_COMPLETED,
    ) -> User:
        """Set a new password during a forgot-password flow.

        There is no current password to verify — possession of the single-use reset
        token is the proof (that check belongs to the recovery service). The full
        discipline still applies: complexity, no-reuse, argon2id, history, lifecycle
        stamp, audit. Then **every** session is revoked (§13): a reset exists for the
        compromised-account case, so no live session may survive it.
        """
        self._apply_new_password(
            user,
            new_password,
            actor=actor or user,
            context=context,
            event=event,
            metadata={"via": "recovery"},
        )
        self._revoke_sessions(user.id, "PASSWORD_RESET")
        self.db.commit()
        return user

    # ------------------------------------------------------------------ #
    # New-account credential (registration) — stamp expiry, no history/reuse
    # ------------------------------------------------------------------ #
    def initialize_password_lifecycle(self, user: User) -> None:
        """Stamp ``password_changed_at``/``password_expires_at`` for a freshly
        created account whose hash was set directly (registration path). Idempotent:
        only fills the fields when they are unset, so it never disturbs a real change.
        """
        if user.password_changed_at is not None:
            return
        now = _now()
        user.password_changed_at = now
        user.password_expires_at = self.policy.expires_at_from(now)
