"""SessionSecurityService — score sessions and detect suspicious behaviour (SRS §15).

Scoring starts at 100 and subtracts for each risk signal. The score is *advisory*:
it drives the UI badge, notifications and (later) step-up policy. Only two things
actually block a session today — a BLOCKED device, and refresh-token reuse — and
both are hard rules, not score thresholds. A security control that can be tuned
away by adjusting a weight is not a control.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.models.enums import (
    SessionRevocationReason,
    SessionSecurityBand,
    SessionStatus,
)
from app.identity.models.session import UserDevice, UserSession
from app.identity.repositories.session_repository import SessionRepository


@dataclass
class RiskAssessment:
    """Transparent scoring: the breakdown is stored on the security event so an
    analyst can see *why* a session scored what it did."""

    score: int
    signals: list[str] = field(default_factory=list)

    @property
    def band(self) -> SessionSecurityBand:
        return SessionSecurityBand.for_score(self.score)


class SessionSecurityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.events = SecurityEventService(db)

    # ------------------------------------------------------------------ #
    # Scoring at login (SRS §15)
    # ------------------------------------------------------------------ #
    def assess_login(
        self,
        user_id: uuid.UUID,
        *,
        device: UserDevice | None,
        is_new_device: bool,
        country: str | None,
    ) -> RiskAssessment:
        score = 100
        signals: list[str] = []

        # "New" is only meaningful relative to a baseline. On a user's first-ever
        # login every device and every country is new by definition, so scoring it
        # as risky would flag every new account and train operators to ignore the
        # signal. Callers invoke this *before* the session is created, so an empty
        # history means "first login".
        has_history = bool(self.sessions.list_for_user(user_id, limit=1))
        if not has_history:
            return RiskAssessment(score=score, signals=signals)

        # A device the user has explicitly trusted absorbs the new-device penalty.
        if is_new_device and not (device is not None and device.trusted):
            score -= settings.SESSION_SCORE_NEW_DEVICE_PENALTY
            signals.append("new_device")

        if country and not self.sessions.has_seen_country(user_id, country):
            score -= settings.SESSION_SCORE_NEW_COUNTRY_PENALTY
            signals.append("new_country")

        return RiskAssessment(score=max(0, min(100, score)), signals=signals)

    # ------------------------------------------------------------------ #
    # Suspicious behaviour (SRS §9, §15)
    # ------------------------------------------------------------------ #
    def penalise(self, session: UserSession, penalty: int, signal: str) -> RiskAssessment:
        session.security_score = max(0, session.security_score - penalty)
        self.db.flush()
        return RiskAssessment(score=session.security_score, signals=[signal])

    def flag_token_reuse(self, session: UserSession) -> RiskAssessment:
        """Refresh-token reuse is the strongest theft signal we have. It is not a
        score adjustment that might leave the session usable — it terminates it."""
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.SUSPICIOUS.value
        session.security_score = max(
            0, session.security_score - settings.SESSION_SCORE_TOKEN_REUSE_PENALTY
        )
        if session.revoked_at is None:
            session.revoked_at = now
            session.revoked_reason = SessionRevocationReason.TOKEN_REUSE.value
        self.db.flush()
        # The event is named for the state the session just entered. Callers also
        # emit TOKEN_REUSE_DETECTED (what happened to the *token*); this records
        # what happened to the *session* (SRS §26).
        self.events.record(
            AuthEventType.SESSION_SUSPICIOUS,
            auth_method=AuthMethod.REFRESH_TOKEN,
            identity_type="HUMAN_USER",
            organization_id=session.organization_id,
            identity_id=session.user_id,
            ip_address=session.ip_address,
            metadata={
                "session_id": str(session.id),
                "signal": "refresh_token_reuse",
                "security_score": session.security_score,
                "band": SessionSecurityBand.for_score(session.security_score).value,
            },
        )
        return RiskAssessment(score=session.security_score, signals=["refresh_token_reuse"])

    @staticmethod
    def band_for(session: UserSession) -> SessionSecurityBand:
        return SessionSecurityBand.for_score(session.security_score)
