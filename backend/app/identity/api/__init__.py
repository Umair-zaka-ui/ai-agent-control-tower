"""Identity REST API (SRS §9 api, §17 versioning). Endpoints only — no logic."""

from app.identity.api.router import identity_router

__all__ = ["identity_router"]
