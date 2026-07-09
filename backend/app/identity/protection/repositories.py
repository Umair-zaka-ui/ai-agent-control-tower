"""Repositories for the account-protection tables (4.2.2.3.4 §17, §20)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.identity.models.login_history import LoginHistory
from app.identity.models.protection import (
    AccountLock,
    BlockedIp,
    IdentityProtectionRule,
    IdentityRiskEvent,
)
from app.identity.protection.enums import AccountLockStatus
from app.identity.repositories.base import BaseRepository


class AccountLockRepository(BaseRepository[AccountLock]):
    model = AccountLock

    def active_for_user(self, user_id: uuid.UUID) -> AccountLock | None:
        stmt = (
            select(AccountLock)
            .where(
                AccountLock.user_id == user_id,
                AccountLock.status == AccountLockStatus.ACTIVE.value,
            )
            .order_by(AccountLock.locked_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def count_for_user(self, user_id: uuid.UUID) -> int:
        """How many times this account has been locked — drives progressive duration."""
        stmt = select(func.count()).select_from(AccountLock).where(AccountLock.user_id == user_id)
        return int(self.db.execute(stmt).scalar() or 0)

    def list_for_organization(
        self, organization_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[AccountLock]:
        stmt = select(AccountLock).where(AccountLock.organization_id == organization_id)
        if status:
            stmt = stmt.where(AccountLock.status == status)
        stmt = stmt.order_by(AccountLock.locked_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def list_active_expired(self, now: datetime, *, limit: int = 500) -> list[AccountLock]:
        stmt = select(AccountLock).where(
            AccountLock.status == AccountLockStatus.ACTIVE.value,
            AccountLock.expires_at.is_not(None),
            AccountLock.expires_at <= now,
        )
        return list(self.db.execute(stmt.limit(limit)).scalars().all())


class BlockedIpRepository(BaseRepository[BlockedIp]):
    model = BlockedIp

    def find_active(
        self, ip_address: str, *, organization_id: uuid.UUID | None, now: datetime
    ) -> BlockedIp | None:
        """A block matches if the IP matches AND it is either global or this org, AND
        it has not lapsed."""
        stmt = select(BlockedIp).where(
            BlockedIp.ip_address == ip_address,
            (BlockedIp.expires_at.is_(None)) | (BlockedIp.expires_at > now),
        )
        if organization_id is not None:
            stmt = stmt.where(
                (BlockedIp.organization_id == organization_id)
                | (BlockedIp.organization_id.is_(None))
            )
        return self.db.execute(stmt.limit(1)).scalars().first()

    def list_for_scope(self, organization_id: uuid.UUID, *, limit: int = 200) -> list[BlockedIp]:
        stmt = (
            select(BlockedIp)
            .where(
                (BlockedIp.organization_id == organization_id)
                | (BlockedIp.organization_id.is_(None))
            )
            .order_by(BlockedIp.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


class IdentityProtectionRuleRepository(BaseRepository[IdentityProtectionRule]):
    model = IdentityProtectionRule

    def list_enabled(self, organization_id: uuid.UUID) -> list[IdentityProtectionRule]:
        """Highest priority first — the first matching rule wins."""
        stmt = (
            select(IdentityProtectionRule)
            .where(
                IdentityProtectionRule.organization_id == organization_id,
                IdentityProtectionRule.enabled.is_(True),
            )
            .order_by(IdentityProtectionRule.priority.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_organization(self, organization_id: uuid.UUID) -> list[IdentityProtectionRule]:
        stmt = (
            select(IdentityProtectionRule)
            .where(IdentityProtectionRule.organization_id == organization_id)
            .order_by(IdentityProtectionRule.priority.desc())
        )
        return list(self.db.execute(stmt).scalars().all())


class IdentityRiskEventRepository(BaseRepository[IdentityRiskEvent]):
    model = IdentityRiskEvent

    def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[IdentityRiskEvent]:
        stmt = select(IdentityRiskEvent).where(
            IdentityRiskEvent.organization_id == organization_id
        )
        if risk_level:
            stmt = stmt.where(IdentityRiskEvent.risk_level == risk_level)
        stmt = stmt.order_by(IdentityRiskEvent.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def count_high_risk_since(self, organization_id: uuid.UUID, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(IdentityRiskEvent)
            .where(
                IdentityRiskEvent.organization_id == organization_id,
                IdentityRiskEvent.created_at >= since,
                IdentityRiskEvent.risk_level.in_(("HIGH", "CRITICAL", "SEVERE")),
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)


class LoginAttemptQuery:
    """Reads over the (extended) ``login_history`` table — the login-attempts record.

    Not a BaseRepository: it only queries, and the writes still go through
    ``LoginHistoryService`` so there is one writer.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def failures_from_ip(self, ip_address: str, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(LoginHistory)
            .where(
                LoginHistory.ip_address == ip_address,
                LoginHistory.success.is_(False),
                LoginHistory.created_at >= since,
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)

    def distinct_accounts_failed_from_ip(self, ip_address: str, since: datetime) -> int:
        stmt = (
            select(func.count(func.distinct(LoginHistory.email)))
            .where(
                LoginHistory.ip_address == ip_address,
                LoginHistory.success.is_(False),
                LoginHistory.created_at >= since,
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)

    def failures_for_email(self, email: str, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(LoginHistory)
            .where(
                LoginHistory.email == email,
                LoginHistory.success.is_(False),
                LoginHistory.created_at >= since,
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)

    def last_success(self, email: str) -> LoginHistory | None:
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.email == email, LoginHistory.success.is_(True))
            .order_by(LoginHistory.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        success: bool | None = None,
        limit: int = 100,
    ) -> list[LoginHistory]:
        stmt = select(LoginHistory).where(LoginHistory.organization_id == organization_id)
        if success is not None:
            stmt = stmt.where(LoginHistory.success.is_(success))
        stmt = stmt.order_by(LoginHistory.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def count_failures_today(self, organization_id: uuid.UUID, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(LoginHistory)
            .where(
                LoginHistory.organization_id == organization_id,
                LoginHistory.success.is_(False),
                LoginHistory.created_at >= since,
            )
        )
        return int(self.db.execute(stmt).scalar() or 0)
