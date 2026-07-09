"""Account-protection admin endpoints (4.2.2.3.4 §20).

    GET    /api/v1/security/account-protection/summary
    GET    /api/v1/security/login-attempts
    GET    /api/v1/security/risk-events
    GET    /api/v1/security/account-locks
    POST   /api/v1/security/account-locks/{id}/unlock
    POST   /api/v1/security/users/{id}/lock
    POST   /api/v1/security/users/{id}/unlock
    GET    /api/v1/security/blocked-ips
    POST   /api/v1/security/blocked-ips
    DELETE /api/v1/security/blocked-ips/{id}
    GET/POST/PUT/DELETE /api/v1/security/identity-protection-rules[/{id}]

All gated by the ``security.protection`` permission and scoped to the caller's
organization. Every lock/unlock/block/rule change is audited (§29, §31, §33).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.api.deps import require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.identity.protection.enums import AccountLockReason
from app.identity.protection.lockout import AccountLockoutService
from app.identity.protection.policy import BlockedIpService, IdentityProtectionRuleService
from app.identity.protection.repositories import (
    AccountLockRepository,
    IdentityRiskEventRepository,
    IdentityProtectionRuleRepository,
    LoginAttemptQuery,
)
from app.identity.protection.schemas import (
    AccountLockRead,
    BlockedIpRead,
    BlockIpRequest,
    LockUserRequest,
    LoginAttemptRead,
    ProtectionRuleRead,
    ProtectionRuleUpdate,
    ProtectionRuleWrite,
    ProtectionSummary,
    RiskEventRead,
    UnlockRequest,
)
from app.identity.models.protection import AccountLock, BlockedIp, IdentityProtectionRule
from app.models.user import User

router = APIRouter(prefix="/api/v1/security", tags=["security:protection"])

_PERM = "security.protection"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Dashboard summary (§23)
# --------------------------------------------------------------------------- #
@router.get("/account-protection/summary", response_model=ProtectionSummary)
def summary(actor: User = Depends(require_permission(_PERM)), db: Session = Depends(get_db)) -> ProtectionSummary:
    org = actor.organization_id
    attempts = LoginAttemptQuery(db)
    since_today = _now() - timedelta(hours=24)
    locks = AccountLockRepository(db).list_for_organization(org, status="ACTIVE", limit=1000)
    risk_repo = IdentityRiskEventRepository(db)
    return ProtectionSummary(
        failed_logins_today=attempts.count_failures_today(org, since_today),
        locked_accounts=len(locks),
        high_risk_attempts=risk_repo.count_high_risk_since(org, since_today),
        blocked_ips=len(BlockedIpService(db).list_for_scope(org)),
        active_rules=len(IdentityProtectionRuleRepository(db).list_enabled(org)),
        risk_events_recent=len(risk_repo.list_for_organization(org, limit=100)),
    )


# --------------------------------------------------------------------------- #
# Login attempts (§25)
# --------------------------------------------------------------------------- #
@router.get("/login-attempts", response_model=list[LoginAttemptRead])
def login_attempts(
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
    success: bool | None = None,
    limit: int = 100,
) -> list[LoginAttemptRead]:
    rows = LoginAttemptQuery(db).list_for_organization(
        actor.organization_id, success=success, limit=min(max(limit, 1), 500)
    )
    return [LoginAttemptRead.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- #
# Risk events (§26)
# --------------------------------------------------------------------------- #
@router.get("/risk-events", response_model=list[RiskEventRead])
def risk_events(
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
    risk_level: str | None = None,
    limit: int = 100,
) -> list[RiskEventRead]:
    rows = IdentityRiskEventRepository(db).list_for_organization(
        actor.organization_id, risk_level=risk_level, limit=min(max(limit, 1), 500)
    )
    return [RiskEventRead.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- #
# Account locks (§24)
# --------------------------------------------------------------------------- #
def _lock_read(db: Session, lock: AccountLock) -> AccountLockRead:
    dto = AccountLockRead.model_validate(lock)
    user = db.get(User, lock.user_id)
    dto.user_email = user.email if user else None
    dto.risk_score = (lock.meta or {}).get("failures")
    return dto


@router.get("/account-locks", response_model=list[AccountLockRead])
def account_locks(
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
    status_filter: str | None = None,
    limit: int = 100,
) -> list[AccountLockRead]:
    rows = AccountLockRepository(db).list_for_organization(
        actor.organization_id, status=status_filter, limit=min(max(limit, 1), 500)
    )
    return [_lock_read(db, r) for r in rows]


def _load_lock(db: Session, actor: User, lock_id: uuid.UUID) -> AccountLock:
    lock = db.get(AccountLock, lock_id)
    if lock is None or lock.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.ACCOUNT_LOCK_NOT_FOUND, "Account lock does not exist.")
    return lock


@router.post("/account-locks/{lock_id}/unlock", response_model=AccountLockRead)
def unlock_lock(
    lock_id: uuid.UUID,
    payload: UnlockRequest,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> AccountLockRead:
    lock = _load_lock(db, actor, lock_id)
    AccountLockoutService(db).unlock(lock, actor_id=actor.id, reason=payload.reason)
    db.commit()
    return _lock_read(db, lock)


@router.post("/users/{user_id}/lock", response_model=AccountLockRead)
def lock_user(
    user_id: uuid.UUID,
    payload: LockUserRequest,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> AccountLockRead:
    target = db.get(User, user_id)
    if target is None or target.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    try:
        reason = AccountLockReason(payload.reason)
    except ValueError:
        reason = AccountLockReason.ADMIN_LOCKED
    result = AccountLockoutService(db).lock(
        target, reason=reason, actor_id=actor.id, metadata={"by_admin": True, "comment": payload.comment}
    )
    db.commit()
    return _lock_read(db, result.lock)


@router.post("/users/{user_id}/unlock", response_model=list[AccountLockRead])
def unlock_user(
    user_id: uuid.UUID,
    payload: UnlockRequest,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> list[AccountLockRead]:
    """Lift every active lock on a user (§29)."""
    target = db.get(User, user_id)
    if target is None or target.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    service = AccountLockoutService(db)
    repo = AccountLockRepository(db)
    unlocked: list[AccountLock] = []
    for lock in repo.list_for_organization(actor.organization_id, status="ACTIVE", limit=1000):
        if lock.user_id == user_id:
            service.unlock(lock, actor_id=actor.id, reason=payload.reason)
            unlocked.append(lock)
    db.commit()
    return [_lock_read(db, lock) for lock in unlocked]


# --------------------------------------------------------------------------- #
# Blocked IPs (§16)
# --------------------------------------------------------------------------- #
@router.get("/blocked-ips", response_model=list[BlockedIpRead])
def list_blocked_ips(
    actor: User = Depends(require_permission(_PERM)), db: Session = Depends(get_db)
) -> list[BlockedIpRead]:
    return [BlockedIpRead.model_validate(e) for e in BlockedIpService(db).list_for_scope(actor.organization_id)]


@router.post("/blocked-ips", response_model=BlockedIpRead, status_code=201)
def block_ip(
    payload: BlockIpRequest,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> BlockedIpRead:
    expires_at = (
        _now() + timedelta(minutes=payload.expires_in_minutes)
        if payload.expires_in_minutes
        else None
    )
    entry = BlockedIpService(db).block(
        payload.ip_address,
        organization_id=None if payload.global_scope else actor.organization_id,
        reason=payload.reason,
        expires_at=expires_at,
        actor_id=actor.id,
    )
    db.commit()
    return BlockedIpRead.model_validate(entry)


@router.delete("/blocked-ips/{blocked_ip_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def unblock_ip(
    blocked_ip_id: uuid.UUID,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> Response:
    entry = db.get(BlockedIp, blocked_ip_id)
    # An org admin may only remove blocks in their own scope (their org or global ones).
    if entry is None or (entry.organization_id not in (None, actor.organization_id)):
        raise IdentityError(ErrorCode.BLOCKED_IP_NOT_FOUND, "Blocked IP does not exist.")
    BlockedIpService(db).unblock(entry, actor_id=actor.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Identity protection rules (§27)
# --------------------------------------------------------------------------- #
@router.get("/identity-protection-rules", response_model=list[ProtectionRuleRead])
def list_rules(
    actor: User = Depends(require_permission(_PERM)), db: Session = Depends(get_db)
) -> list[ProtectionRuleRead]:
    return [
        ProtectionRuleRead.model_validate(r)
        for r in IdentityProtectionRuleService(db).list_for_organization(actor.organization_id)
    ]


@router.post("/identity-protection-rules", response_model=ProtectionRuleRead, status_code=201)
def create_rule(
    payload: ProtectionRuleWrite,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> ProtectionRuleRead:
    rule = IdentityProtectionRuleService(db).create(
        actor.organization_id,
        name=payload.name,
        conditions=payload.conditions,
        decision=payload.decision,
        description=payload.description,
        priority=payload.priority,
        enabled=payload.enabled,
        actor_id=actor.id,
    )
    db.commit()
    return ProtectionRuleRead.model_validate(rule)


def _load_rule(db: Session, actor: User, rule_id: uuid.UUID) -> IdentityProtectionRule:
    rule = db.get(IdentityProtectionRule, rule_id)
    if rule is None or rule.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.PROTECTION_RULE_NOT_FOUND, "Protection rule does not exist.")
    return rule


@router.put("/identity-protection-rules/{rule_id}", response_model=ProtectionRuleRead)
def update_rule(
    rule_id: uuid.UUID,
    payload: ProtectionRuleUpdate,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> ProtectionRuleRead:
    rule = _load_rule(db, actor, rule_id)
    IdentityProtectionRuleService(db).update(rule, actor_id=actor.id, **payload.model_dump(exclude_none=True))
    db.commit()
    return ProtectionRuleRead.model_validate(rule)


@router.delete("/identity-protection-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_rule(
    rule_id: uuid.UUID,
    actor: User = Depends(require_permission(_PERM)),
    db: Session = Depends(get_db),
) -> Response:
    rule = _load_rule(db, actor, rule_id)
    IdentityProtectionRuleService(db).delete(rule, actor_id=actor.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
