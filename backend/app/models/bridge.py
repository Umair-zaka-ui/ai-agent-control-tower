"""Phase 5.7 (M5.7) - External Agent Governance Bridge.

Three additive tables. **None of them is a second agent registry** (the one
canonical registry is still ``agents``; M5.1's guard forbids
``external_agents``/``agents_v2``) and **none of them is a second authorizer**
-- every boundary call authorizes through the existing
``AuthorizationGateway``; the rows here record *what it decided*, they do not
decide.

**The enforcement mode is NOT one of these tables.** It is a derived function
of ``agents.control_state`` plus one nullable column
(``agents.external_enforcement_mode``) -- see ``app/bridge/modes.py``. The
consequence is structural and is the point of the design:
``'NATIVE_ENFORCED'`` is **not a storable value anywhere in this schema** (a
CHECK constraint restricts the column to OBSERVED/ADVISORY/GATEWAY_ENFORCED),
so no row can ever claim full enforcement. Full enforcement is reachable only
by *actually being* ``control_state='GOVERNED'`` -- the same single signal
Phase 5.6's truthful-containment gate reads.

  * ``external_capability_grants`` -- one scoped, expiring, revocable
    credential an agent **outside** ACT uses to call enterprise capability
    *through* ACT's boundary. It is **not an internal principal**: no
    ``users`` row, no role, no session. Authentication is a signed request
    (HMAC-SHA256 over method/path/timestamp/nonce/body-digest) whose secret
    is stored only as Fernet ciphertext via M4.11's ``credential_crypto``.
    *Why new:* ``AgentApiKey`` is an unscoped bearer credential for a native
    agent -- it carries no capability scope, no expiry semantics of this
    shape, no rate limit and no replay protection, and being a bearer token
    it cannot be replay-protected at all.

  * ``external_request_nonces`` -- the replay-protection ledger. One row per
    accepted (grant, nonce); the unique constraint **is** the anti-replay
    primitive, exactly as Phase 3.1's idempotency table uses its own.
    *Why new:* nothing else in the schema records "this exact signed request
    has already been seen".

  * ``external_gateway_calls`` -- one row per boundary decision: the
    capability, the effective enforcement mode at the time, the real
    ``AuthorizationGateway`` verdict, the 4.3 policy outcome, the 4.4 cost
    outcome, allow/deny, the fail-mode that governed it, and what the
    downstream dispatch did. *Why new:* no existing table records "an agent
    ACT does not run called this capability through ACT's boundary and ACT
    allowed or denied it". ``agent_actions`` is the native-agent action
    funnel; ``tool_calls`` belongs to an ``AgentExecution`` this call has
    none of.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

#: The three modes that are *storable*. ``NATIVE_ENFORCED`` is deliberately
#: absent -- see this module's docstring and ``app/bridge/modes.py``.
STORABLE_ENFORCEMENT_MODES = ("OBSERVED", "ADVISORY", "GATEWAY_ENFORCED")

#: The boundary's verdict for one capability call.
GATEWAY_OUTCOMES = ("ALLOWED", "DENIED")

#: What happened downstream *after* the boundary allowed and committed.
#: ``NOT_DISPATCHED`` is the only correct value for a DENIED call -- there is
#: no code path that records a dispatch for a call that was denied.
DISPATCH_STATUSES = ("NOT_DISPATCHED", "DISPATCHED", "DISPATCH_FAILED")

#: Which §9 plane the capability belongs to, and therefore how it fails.
FAIL_MODES = ("FAIL_CLOSED", "FAIL_OPEN")

#: The 4.3 policy outcome at the boundary. ``UNEVALUABLE`` is what makes the
#: fail-closed rule observable: it is recorded, and it denies.
POLICY_OUTCOMES = ("NOT_APPLICABLE", "SATISFIED", "APPROVAL_REQUIRED", "UNEVALUABLE")

#: The 4.4 cost outcome. ``NOT_MEASURABLE`` is the honest value when no budget
#: applies -- ACT does not invent a number for a call it cannot price.
COST_OUTCOMES = ("NOT_MEASURABLE", "WITHIN_BUDGET", "EXCEEDED", "UNEVALUABLE")


class ExternalCapabilityGrant(Base, UUIDPrimaryKeyMixin):
    """A scoped, revocable, replay-protected capability grant for an agent
    that exists **outside** ACT.

    What this row is *not*: an internal identity. It confers no RBAC role, no
    session, no ``users`` row and no ability to reach any surface other than
    the boundary endpoint, whose every call is authorized by the existing
    ``AuthorizationGateway`` against the *agent* principal. It is a bound on
    reach, never a source of authority."""

    __tablename__ = "external_capability_grants"
    __table_args__ = (
        UniqueConstraint("key_id", name="uq_ext_grants_key_id"),
        UniqueConstraint("organization_id", "agent_id", "label",
                         name="uq_ext_grants_org_agent_label"),
        CheckConstraint("rate_limit_per_minute > 0", name="ck_ext_grants_rate_limit"),
        Index("ix_ext_grants_org_agent", "organization_id", "agent_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: The one canonical registry -- never a copy of the agent.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The public half the external agent sends in ``X-ACT-Key-Id``. Safe to
    #: log and safe to audit; it identifies, it does not authenticate.
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Fernet ciphertext of the signing secret (M4.11 ``credential_crypto``).
    #: The plaintext is returned to the caller exactly once, at issue.
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    #: A masked hint for the UI. Never enough to reconstruct the secret.
    secret_hint: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The scope: a list of ``{"capability": str, "target_ref": str|null}``
    #: entries. A call outside this list is denied at the boundary *before*
    #: anything is dispatched. Bounds reach; grants none.
    scope: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalRequestNonce(Base, UUIDPrimaryKeyMixin):
    """One accepted signed request. The unique constraint on
    ``(grant_id, nonce)`` is the replay defense itself: a second presentation
    of the same nonce cannot commit, so it cannot be executed."""

    __tablename__ = "external_request_nonces"
    __table_args__ = (
        UniqueConstraint("grant_id", "nonce", name="uq_ext_nonce_grant_nonce"),
        Index("ix_ext_nonce_expires", "expires_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_capability_grants.id", ondelete="CASCADE"),
        nullable=False,
    )
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Past this instant the nonce may be reaped -- the signature's own
    #: timestamp window has already made the request unreplayable by then.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalGatewayCall(Base, UUIDPrimaryKeyMixin):
    """One boundary decision, recorded truthfully.

    ``enforcement_mode_at_time`` is stored rather than re-derived because the
    honest question an auditor asks later is "what did ACT claim it could do
    *when it decided this*" -- a mode transition afterwards must not rewrite
    the answer."""

    __tablename__ = "external_gateway_calls"
    __table_args__ = (
        CheckConstraint(f"outcome IN {GATEWAY_OUTCOMES}", name="ck_ext_calls_outcome"),
        CheckConstraint(f"dispatch_status IN {DISPATCH_STATUSES}", name="ck_ext_calls_dispatch"),
        CheckConstraint(f"fail_mode IN {FAIL_MODES}", name="ck_ext_calls_fail_mode"),
        CheckConstraint(f"policy_outcome IN {POLICY_OUTCOMES}", name="ck_ext_calls_policy"),
        CheckConstraint(f"cost_outcome IN {COST_OUTCOMES}", name="ck_ext_calls_cost"),
        # A denied call can never carry a dispatch. Enforced by the database,
        # not merely by the code path that writes it.
        CheckConstraint("outcome = 'ALLOWED' OR dispatch_status = 'NOT_DISPATCHED'",
                        name="ck_ext_calls_denied_never_dispatched"),
        Index("ix_ext_calls_org_agent_created", "organization_id", "agent_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: SET NULL, not CASCADE: deleting a grant must not erase the evidence of
    #: what it was used for.
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_capability_grants.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    capability_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enforcement_mode_at_time: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- the real AuthorizationGateway verdict (never re-decided here) ---
    authz_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    authz_permission: Mapped[str] = mapped_column(String(128), nullable=False)
    authz_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    authz_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    policy_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    cost_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fail_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    dispatch_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NOT_DISPATCHED", server_default="NOT_DISPATCHED"
    )
    #: Never the response body, never a credential -- a bounded summary only.
    dispatch_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "STORABLE_ENFORCEMENT_MODES",
    "GATEWAY_OUTCOMES",
    "DISPATCH_STATUSES",
    "FAIL_MODES",
    "POLICY_OUTCOMES",
    "COST_OUTCOMES",
    "ExternalCapabilityGrant",
    "ExternalRequestNonce",
    "ExternalGatewayCall",
]
