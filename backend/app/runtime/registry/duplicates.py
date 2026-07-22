"""Phase 5.1 SRS §32-§33, §64 — exact + similarity duplicate detection.

No fuzzy-matching library is installed in this codebase and none is needed
at this scale — similarity scoring uses stdlib ``difflib.SequenceMatcher``,
which is more than adequate for name/description/business-purpose comparison
across an organization's agent inventory (typically hundreds, not millions,
of rows).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.agent_registry import AgentDuplicateMatch
from app.models.runtime import AgentDefinition
from app.models.user import User
from app.runtime.services import _now, _record_event

_SIMILAR_THRESHOLD = 0.72
_LIKELY_THRESHOLD = 0.85


def _ratio(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


class AgentDuplicateDetectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check(self, actor: User, agent: Agent) -> list[AgentDuplicateMatch]:
        """§32.1/§32.2 — runs both exact and similarity checks against every
        other agent in the same organization, persists a row per candidate
        that matched anything, and returns them."""
        candidates = list(self.db.execute(
            select(Agent).where(Agent.organization_id == agent.organization_id, Agent.id != agent.id)
        ).scalars())
        definition = self._latest_definition(agent.id)

        results: list[AgentDuplicateMatch] = []
        for candidate in candidates:
            exact_fields = self._exact_match_fields(agent, candidate, definition)
            if exact_fields:
                results.append(self._record(agent, candidate, "EXACT", Decimal("100.00"), exact_fields,
                                             "CONFIRMED_DUPLICATE"))
                continue

            score, fields = self._similarity(agent, candidate)
            if score >= _LIKELY_THRESHOLD:
                results.append(self._record(agent, candidate, "SIMILAR", Decimal(str(round(score * 100, 2))),
                                             fields, "LIKELY_DUPLICATE"))
            elif score >= _SIMILAR_THRESHOLD:
                results.append(self._record(agent, candidate, "SIMILAR", Decimal(str(round(score * 100, 2))),
                                             fields, "POSSIBLE_DUPLICATE"))

        if results:
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_DUPLICATE_DETECTED, actor,
                         organization_id=agent.organization_id, agent_id=agent.id,
                         meta={"candidate_count": len(results)})
        self.db.commit()
        for r in results:
            self.db.refresh(r)
        return results

    def _exact_match_fields(self, agent: Agent, candidate: Agent, definition) -> list[str]:
        """§32.1."""
        fields = []
        if agent.slug and candidate.slug and agent.slug == candidate.slug:
            fields.append("slug")
        if agent.external_reference and candidate.external_reference and \
                agent.external_reference == candidate.external_reference:
            fields.append("external_reference")
        if agent.identity_id and candidate.identity_id and agent.identity_id == candidate.identity_id:
            fields.append("identity_id")
        if definition is not None and definition.entrypoint:
            candidate_def = self._latest_definition(candidate.id)
            if candidate_def is not None and candidate_def.entrypoint == definition.entrypoint:
                if agent.repository_url and agent.repository_url == candidate.repository_url:
                    fields.append("repository+entrypoint")
                if definition.entrypoint_type == "HTTP_ENDPOINT":
                    fields.append("http_endpoint")
                if definition.entrypoint_type == "CONTAINER_IMAGE" and \
                        (agent.business_purpose or "") == (candidate.business_purpose or "") and \
                        agent.business_purpose:
                    fields.append("container_image+purpose")
        if agent.project_id and candidate.project_id == agent.project_id and \
                agent.name.strip().lower() == candidate.name.strip().lower():
            fields.append("project+normalized_name")
        return fields

    def _similarity(self, agent: Agent, candidate: Agent) -> tuple[float, list[str]]:
        """§32.2 — averaged similarity across name/description/business_purpose,
        weighted toward name (the strongest duplicate signal)."""
        name_score = _ratio(agent.name, candidate.name)
        desc_score = _ratio(agent.description, candidate.description)
        purpose_score = _ratio(agent.business_purpose, candidate.business_purpose)
        weighted = name_score * 0.5 + desc_score * 0.25 + purpose_score * 0.25
        fields = []
        if name_score >= _SIMILAR_THRESHOLD:
            fields.append("name")
        if desc_score >= _SIMILAR_THRESHOLD:
            fields.append("description")
        if purpose_score >= _SIMILAR_THRESHOLD:
            fields.append("business_purpose")
        if agent.owner_id and agent.owner_id == candidate.owner_id:
            fields.append("owner")
        return weighted, fields

    def _record(self, agent: Agent, candidate: Agent, match_type: str, score: Decimal,
               fields: list[str], status: str) -> AgentDuplicateMatch:
        """Idempotent per (source, candidate) pair regardless of review
        state — re-running the check must not spawn a second, unreviewed
        row for a pair someone already reviewed (that would silently
        re-block registration after a reviewer justified it as separate)."""
        existing = self.db.execute(
            select(AgentDuplicateMatch).where(
                AgentDuplicateMatch.source_agent_id == agent.id,
                AgentDuplicateMatch.candidate_agent_id == candidate.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.match_type, existing.confidence_score = match_type, score
            existing.matching_fields = fields
            if existing.review_decision is None:
                existing.status = status
            self.db.add(existing)
            return existing
        match = AgentDuplicateMatch(
            source_agent_id=agent.id, candidate_agent_id=candidate.id, match_type=match_type,
            confidence_score=score, matching_fields=fields, status=status,
        )
        self.db.add(match)
        self.db.flush()
        return match

    def list_matches(self, agent_id: uuid.UUID) -> list[AgentDuplicateMatch]:
        stmt = select(AgentDuplicateMatch).where(
            (AgentDuplicateMatch.source_agent_id == agent_id) |
            (AgentDuplicateMatch.candidate_agent_id == agent_id)
        )
        return list(self.db.execute(stmt.order_by(AgentDuplicateMatch.created_at.desc())).scalars())

    def review(self, actor: User, match_id: uuid.UUID, *, decision: str, reason: str) -> AgentDuplicateMatch:
        """§64 — CONFIRM_DUPLICATE / NOT_DUPLICATE / MERGE_REQUIRED /
        JUSTIFIED_SEPARATE_AGENT. Overrides are always audited (§32.4)."""
        match = self.db.get(AgentDuplicateMatch, match_id)
        if match is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Duplicate match not found.")
        match.reviewed_by = actor.id
        match.review_decision = decision
        match.review_reason = reason
        match.reviewed_at = _now()
        if decision == "CONFIRM_DUPLICATE":
            match.status = "CONFIRMED_DUPLICATE"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_DUPLICATE_REVIEWED, actor,
                     organization_id=self.db.get(Agent, match.source_agent_id).organization_id,
                     agent_id=match.source_agent_id,
                     meta={"match_id": str(match.id), "decision": decision})
        self.db.commit()
        self.db.refresh(match)
        return match

    def has_confirmed_duplicate(self, agent_id: uuid.UUID) -> bool:
        """§32.4 — 'Confirmed duplicates block registration.'"""
        stmt = select(AgentDuplicateMatch.id).where(
            AgentDuplicateMatch.source_agent_id == agent_id,
            AgentDuplicateMatch.status == "CONFIRMED_DUPLICATE",
        ).limit(1)
        return self.db.execute(stmt).first() is not None

    def blocking_match(self, agent_id: uuid.UUID) -> AgentDuplicateMatch | None:
        """§32.4 — 'Confirmed duplicates block registration. Likely
        duplicates require justification or merge.' A LIKELY_DUPLICATE
        match blocks only until reviewed (any decision — including
        JUSTIFIED_SEPARATE_AGENT — clears it; CONFIRM_DUPLICATE promotes it
        to CONFIRMED_DUPLICATE, which then blocks unconditionally).
        POSSIBLE_DUPLICATE is a warning only and never blocks."""
        stmt = select(AgentDuplicateMatch).where(
            AgentDuplicateMatch.source_agent_id == agent_id,
            AgentDuplicateMatch.status == "CONFIRMED_DUPLICATE",
        ).limit(1)
        confirmed = self.db.execute(stmt).scalar_one_or_none()
        if confirmed is not None:
            return confirmed
        stmt = select(AgentDuplicateMatch).where(
            AgentDuplicateMatch.source_agent_id == agent_id,
            AgentDuplicateMatch.status == "LIKELY_DUPLICATE",
            AgentDuplicateMatch.review_decision.is_(None),
        ).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def _latest_definition(self, agent_id: uuid.UUID) -> AgentDefinition | None:
        return self.db.execute(
            select(AgentDefinition).where(AgentDefinition.agent_id == agent_id)
            .order_by(AgentDefinition.created_at.desc()).limit(1)
        ).scalar_one_or_none()
