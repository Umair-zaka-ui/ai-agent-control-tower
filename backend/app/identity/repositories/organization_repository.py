"""Organization aggregate repository (SRS §16)."""

from __future__ import annotations

from app.identity.repositories.base import BaseRepository
from app.models.organization import Organization


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization
