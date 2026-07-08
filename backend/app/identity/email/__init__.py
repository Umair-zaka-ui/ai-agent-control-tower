"""Transactional onboarding email (4.2.2.3.1 §6)."""

from app.identity.email.service import (
    EmailResult,
    EmailService,
    invitation_url,
    verification_url,
)

__all__ = ["EmailService", "EmailResult", "invitation_url", "verification_url"]
