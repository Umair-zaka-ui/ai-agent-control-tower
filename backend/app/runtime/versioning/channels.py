"""Phase 5.2 Part 1 SRS §9, §26 — release channel catalog.

Global, not per-organization (no SRS bullet asks for org-scoped channels,
and a shared STABLE/BETA/CANARY/INTERNAL vocabulary keeps release-channel
badges comparable across tenants) — migration 0025 seeds the four defaults;
``ensure_seeded`` is a defensive get-or-create for any environment where the
migration's seed rows were somehow removed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentReleaseChannel

_DEFAULTS = (
    ("STABLE", "Generally available releases.", True),
    ("BETA", "Pre-release, opt-in testing.", False),
    ("CANARY", "Early-access, small-blast-radius rollout.", False),
    ("INTERNAL", "Internal-only, never customer-facing.", False),
)


class ReleaseChannelService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[AgentReleaseChannel]:
        return list(self.db.execute(select(AgentReleaseChannel).order_by(AgentReleaseChannel.name)).scalars())

    def ensure_seeded(self) -> None:
        existing = {c.name for c in self.list()}
        for name, description, is_default in _DEFAULTS:
            if name not in existing:
                self.db.add(AgentReleaseChannel(name=name, description=description, is_default=is_default))
        self.db.flush()

    def get_by_name(self, name: str) -> AgentReleaseChannel:
        channel = self.db.execute(
            select(AgentReleaseChannel).where(AgentReleaseChannel.name == name)
        ).scalar_one_or_none()
        if channel is None:
            raise IdentityError(ErrorCode.AGENT_RELEASE_CHANNEL_NOT_FOUND,
                                f"Release channel '{name}' does not exist.")
        return channel

    def default(self) -> AgentReleaseChannel:
        channel = self.db.execute(
            select(AgentReleaseChannel).where(AgentReleaseChannel.is_default.is_(True))
        ).scalars().first()
        if channel is not None:
            return channel
        self.ensure_seeded()
        return self.get_by_name("STABLE")
