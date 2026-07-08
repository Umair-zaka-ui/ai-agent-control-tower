"""Device repository (SRS 4.2.2.2 §22)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.identity.models.enums import DeviceStatus
from app.identity.models.session import UserDevice
from app.identity.repositories.base import BaseRepository


class DeviceRepository(BaseRepository[UserDevice]):
    model = UserDevice

    def get_by_fingerprint(self, user_id: uuid.UUID, fingerprint: str) -> UserDevice | None:
        """A device is unique per (user, fingerprint) — see the unique constraint."""
        stmt = select(UserDevice).where(
            UserDevice.user_id == user_id, UserDevice.fingerprint == fingerprint
        )
        return self.db.execute(stmt).scalars().first()

    def list_for_user(self, user_id: uuid.UUID) -> list[UserDevice]:
        stmt = (
            select(UserDevice)
            .where(UserDevice.user_id == user_id)
            .order_by(UserDevice.last_seen_at.desc().nullslast())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_trusted(self, user_id: uuid.UUID) -> list[UserDevice]:
        stmt = select(UserDevice).where(
            UserDevice.user_id == user_id, UserDevice.status == DeviceStatus.TRUSTED.value
        )
        return list(self.db.execute(stmt).scalars().all())
