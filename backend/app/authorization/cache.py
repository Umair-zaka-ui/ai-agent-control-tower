"""Permission cache + version management (Phase 4.3.2 §10, §18).

Resolving an identity's grants touches roles, hierarchy and permissions — too much
to repeat on every request. So the resolved grant list is cached per identity in
``permission_cache``, tagged with the organization's ``permission_versions`` counter.
Any role/permission/assignment change **bumps the org version**, which invalidates
every cached set for that org at once (no row-by-row deletion needed).

Postgres-backed (ADR-0002: no second datastore).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.authorization.engine import (
    Grant,
    PermissionEngine,
    PermissionResolver,
    ResourceContext,
    AuthorizationResult,
)
from app.core.config import settings
from app.models.rbac import PermissionCache, PermissionVersion
from app.models.user import User


class PermissionCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- version (invalidation token) ------------------------------------ #
    def current_version(self, organization_id: uuid.UUID | None) -> int:
        row = self.db.execute(
            select(PermissionVersion).where(
                PermissionVersion.organization_id.is_(organization_id)
                if organization_id is None
                else PermissionVersion.organization_id == organization_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = PermissionVersion(organization_id=organization_id, version=1)
            self.db.add(row)
            self.db.flush()
        return row.version

    def bump_version(self, organization_id: uuid.UUID | None) -> int:
        """Invalidate every cached permission set for the org (§26)."""
        row = self.db.execute(
            select(PermissionVersion).where(
                PermissionVersion.organization_id.is_(organization_id)
                if organization_id is None
                else PermissionVersion.organization_id == organization_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = PermissionVersion(organization_id=organization_id, version=2)
            self.db.add(row)
        else:
            row.version += 1
            row.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return row.version

    # --- cached grants --------------------------------------------------- #
    def get_grants(self, user: User) -> tuple[list[Grant], bool]:
        """Return (grants, cache_hit). Rebuilds and stores on a miss."""
        if not settings.PERMISSION_CACHE_ENABLED:
            return PermissionResolver(self.db).resolve_grants(user), False

        version = self.current_version(user.organization_id)
        now = datetime.now(timezone.utc)
        row = self.db.execute(
            select(PermissionCache).where(PermissionCache.identity_id == user.id)
        ).scalar_one_or_none()

        if row is not None and row.version == version and row.expires_at > now:
            return [Grant.from_json(g) for g in row.grants_json], True

        grants = PermissionResolver(self.db).resolve_grants(user)
        self._store(user, grants, version, now)
        return grants, False

    def _store(self, user: User, grants: list[Grant], version: int, now: datetime) -> None:
        expires_at = now + timedelta(seconds=settings.PERMISSION_CACHE_TTL_SECONDS)
        payload = [g.to_json() for g in grants]
        stmt = (
            pg_insert(PermissionCache)
            .values(
                id=uuid.uuid4(), identity_id=user.id, organization_id=user.organization_id,
                grants_json=payload, version=version, expires_at=expires_at, created_at=now,
            )
            .on_conflict_do_update(
                index_elements=["identity_id"],
                set_={"grants_json": payload, "version": version,
                      "expires_at": expires_at, "organization_id": user.organization_id},
            )
        )
        try:
            self.db.execute(stmt)
            # Persist so other requests/sessions see it (mirrors the auth-phase
            # commit in get_current_user). Best-effort: a failure just means a miss
            # next time, never a wrong decision.
            self.db.commit()
        except Exception:
            self.db.rollback()

    # --- convenience: cached authorize ----------------------------------- #
    def authorize(
        self, user: User, permission: str, ctx: ResourceContext | None = None
    ) -> tuple[AuthorizationResult, bool]:
        grants, hit = self.get_grants(user)
        result = PermissionEngine(self.db).evaluate(user, permission, grants, ctx)
        return result, hit

    def invalidate_org(self, organization_id: uuid.UUID | None) -> None:
        self.bump_version(organization_id)
