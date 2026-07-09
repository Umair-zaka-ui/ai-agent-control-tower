"""RecoveryService — coordinates the recovery workflow (4.2.2.3.3 §3, §19).

A thin coordinator over the focused services (`PasswordResetService`,
`EmailChangeService`) so a route has one entry point and the session-revocation
dependency is injected in exactly one place. The real logic lives in the services;
this keeps the composition and the audit-context plumbing together.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.identity.auth.enums import AuthEventType
from app.identity.recovery.audit import RecoveryContext
from app.identity.recovery.email_change_service import EmailChangeService
from app.identity.recovery.password_reset_service import PasswordResetService, SessionRevoker
from app.identity.recovery.repository import PasswordResetRepository
from app.models.user import User

# Events surfaced by GET /security/recovery-events (§18).
RECOVERY_EVENT_TYPES = [
    AuthEventType.PASSWORD_RESET_REQUESTED.value,
    AuthEventType.PASSWORD_RESET_COMPLETED.value,
    AuthEventType.PASSWORD_RESET_FAILED.value,
    AuthEventType.EMAIL_CHANGE_REQUESTED.value,
    AuthEventType.EMAIL_CHANGED.value,
    AuthEventType.EMAIL_CHANGE_VERIFIED.value,
    AuthEventType.RECOVERY_REQUEST_EXPIRED.value,
    AuthEventType.RECOVERY_REQUEST_REVOKED.value,
    AuthEventType.EMAIL_VERIFICATION_SENT.value,
    AuthEventType.EMAIL_VERIFIED.value,
]


class RecoveryService:
    def __init__(self, db: Session, *, revoke_sessions: SessionRevoker | None = None) -> None:
        self.db = db
        self.password_reset = PasswordResetService(db, revoke_sessions=revoke_sessions)
        self.email_change = EmailChangeService(db)

    # ---- Password reset (§9, §10) ---- #
    def forgot_password(self, email: str, *, context: RecoveryContext | None = None) -> None:
        self.password_reset.request_reset(email, context=context)

    def reset_password(
        self, token: str, new_password: str, *, context: RecoveryContext | None = None
    ) -> User:
        return self.password_reset.reset(token, new_password, context=context)

    # ---- Email change (§12) ---- #
    def change_email(
        self, user: User, *, new_email: str, current_password: str,
        context: RecoveryContext | None = None,
    ) -> None:
        self.email_change.request_change(
            user, new_email=new_email, current_password=current_password, context=context
        )

    def verify_new_email(self, token: str, *, context: RecoveryContext | None = None) -> User:
        return self.email_change.verify_new_email(token, context=context)

    # ---- Maintenance (§26) ---- #
    def expire_stale(self, *, organization_id: uuid.UUID | None = None) -> int:
        count = self.password_reset.expire_stale(organization_id=organization_id)
        if count:
            self.db.commit()
        return count
