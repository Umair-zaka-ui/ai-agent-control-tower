"""Agent API key service: issuing, authenticating and revoking keys.

Keys are shown to the caller exactly once at creation; only a SHA-256 hash is
stored. Authentication hashes the presented key and looks it up directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ApiKeyStatus
from app.core.security import generate_agent_api_key, hash_api_key
from app.models.agent import Agent
from app.models.api_key import AgentApiKey


def issue_api_key(
    db: Session,
    agent: Agent,
    expires_at: datetime | None = None,
) -> tuple[AgentApiKey, str]:
    """Create a new active API key for ``agent``.

    Returns the persisted record and the **plaintext** key (caller must show it
    once and then discard it).
    """
    raw_key = generate_agent_api_key()
    record = AgentApiKey(
        agent_id=agent.id,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        status=ApiKeyStatus.ACTIVE,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()
    return record, raw_key


def authenticate(db: Session, raw_key: str) -> Agent | None:
    """Resolve an agent from a presented API key, or ``None`` if invalid.

    Validates that the key exists, is ACTIVE, not expired, and that the owning
    agent is ACTIVE. Updates ``last_used_at`` on success.
    """
    record = db.execute(
        select(AgentApiKey).where(AgentApiKey.key_hash == hash_api_key(raw_key))
    ).scalar_one_or_none()

    if record is None or record.status != ApiKeyStatus.ACTIVE:
        return None

    if record.expires_at is not None and record.expires_at < datetime.now(timezone.utc):
        return None

    agent = db.get(Agent, record.agent_id)
    if agent is None:
        return None

    record.last_used_at = datetime.now(timezone.utc)
    db.flush()
    return agent


def list_keys(db: Session, agent_id: uuid.UUID) -> list[AgentApiKey]:
    stmt = (
        select(AgentApiKey)
        .where(AgentApiKey.agent_id == agent_id)
        .order_by(AgentApiKey.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def revoke_key(db: Session, record: AgentApiKey) -> AgentApiKey:
    record.status = ApiKeyStatus.REVOKED
    db.flush()
    return record
