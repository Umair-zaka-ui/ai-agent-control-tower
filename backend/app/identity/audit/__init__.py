"""Identity audit integration (SRS §9 audit, §19)."""

from app.identity.audit.events import record_security_event

__all__ = ["record_security_event"]
