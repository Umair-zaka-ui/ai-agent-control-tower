"""Phase 5.7 (M5.7) - how an agent that exists **outside** ACT proves who it
is, **without ever becoming an internal principal**.

**Why not federation.** OIDC/SAML were the obvious candidate and are the
wrong tool: ``FederationService`` resolves or *provisions a ``User`` row*,
maps group claims onto roles and issues a session
(``_resolve_or_provision_user`` -> ``_provision_user`` -> ``_issue_session``).
Every federated login therefore mints an internal principal with internal
authority -- precisely the privilege escalation this phase forbids. Federation
stays what it is: human and internal SSO.

**Why not a bearer API key.** ``AgentApiKey`` is a bearer credential: whoever
holds the string is the agent. A bearer token cannot be replay-protected --
the token *is* the request's only proof, so a captured request replays
perfectly. It also carries no capability scope and no rate limit.

**What this module does instead: signed requests.** The external agent holds
a secret (never transmitted) and signs each request over its method, path,
timestamp, a single-use nonce, and a digest of the exact body bytes. ACT
recomputes the HMAC with the stored secret and compares in constant time.
That gives all four properties the phase requires at once:

  * **identity** without a ``users`` row -- the grant names an ``agents`` row
    and nothing else. There is no session, no role, no token that any other
    ACT surface will accept;
  * **replay protection** -- a timestamp window plus a
    ``(grant_id, nonce)`` unique constraint. The database, not a cache, is
    the primitive, so two concurrent replays cannot both win;
  * **scope** -- the grant lists the capabilities and targets it may reach,
    and that list bounds reach; it never *grants* authority. Authority is
    decided by ``AuthorizationGateway`` on every single call;
  * **revocation** -- immediate and unconditional, because every call
    re-reads the grant row. Nothing about a grant is cached.

A compromised grant therefore costs the attacker exactly the scoped
capabilities on one agent in one tenant, for as long as it takes an operator
to revoke it -- and cannot be escalated into internal identity by any path,
because there is no path.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.bridge import ExternalCapabilityGrant, ExternalRequestNonce
from app.models.user import User
from app.runtime.providers.credential_crypto import decrypt_secret, encrypt_secret

#: How far a request's timestamp may be from ACT's clock. Wide enough for
#: ordinary clock drift between two machines, narrow enough that the nonce
#: ledger stays small and a captured request expires quickly.
SIGNATURE_WINDOW_SECONDS = 300

#: The signing scheme, named in the header so a future scheme can be added
#: without guessing which one a request used.
SIGNATURE_SCHEME = "ACT-HMAC-SHA256"

HEADER_KEY_ID = "X-ACT-Key-Id"
HEADER_TIMESTAMP = "X-ACT-Timestamp"
HEADER_NONCE = "X-ACT-Nonce"
HEADER_SIGNATURE = "X-ACT-Signature"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def signing_string(*, method: str, path: str, timestamp: str, nonce: str,
                   body: bytes) -> str:
    """The exact bytes both sides sign. Documented and stable: an external
    agent in any language must be able to reproduce it, so it is a simple
    newline-joined form over values that survive transport verbatim, with the
    body reduced to a hex digest rather than re-serialized (re-serializing
    JSON is where cross-language signing schemes usually break)."""
    digest = hashlib.sha256(body or b"").hexdigest()
    return "\n".join([SIGNATURE_SCHEME, method.upper(), path, timestamp, nonce, digest])


def sign(secret: str, *, method: str, path: str, timestamp: str, nonce: str,
         body: bytes) -> str:
    """Produce a signature. Exported because the reference client and the
    tests must sign exactly as ACT verifies -- one implementation, not two."""
    payload = signing_string(method=method, path=path, timestamp=timestamp,
                             nonce=nonce, body=body)
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ExternalIdentity:
    """A verified external caller.

    Note what it does **not** carry: no ``User``, no role set, no session, no
    permission list. It names a grant and the agent that grant is for. Every
    authorization question about it is answered later, by
    ``AuthorizationGateway``, on the agent principal."""

    grant: ExternalCapabilityGrant
    agent: Agent

    @property
    def organization_id(self) -> uuid.UUID:
        return self.grant.organization_id

    def scoped_for(self, capability_key: str, target_ref: str | None) -> bool:
        """Whether this grant's scope covers the call.

        A scope entry with a null ``target_ref`` covers every target *of that
        capability*; it is never a wildcard across capabilities."""
        for entry in self.grant.scope or []:
            if not isinstance(entry, dict) or entry.get("capability") != capability_key:
                continue
            allowed_target = entry.get("target_ref")
            if allowed_target is None or allowed_target == target_ref:
                return True
        return False


class ExternalGrantService:
    """Issues, reads and revokes scoped external-agent grants."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Management (authorized at the route by external_grant.issue)
    # ------------------------------------------------------------------ #
    def issue(self, actor: User, agent: Agent, *, label: str, scope: list[dict],
              expires_at: datetime | None = None,
              rate_limit_per_minute: int = 60) -> tuple[ExternalCapabilityGrant, str]:
        """Create a grant and return it with its **plaintext secret**, which
        the caller must show once and discard. Only the ciphertext is stored.

        A grant scoped to a **governed** capability is refused unless the
        agent's effective mode actually enforces boundary calls: it would be a
        credential for a boundary that, for that agent, enforces nothing --
        the exact shape of an over-claim.

        An **observability** scope (``telemetry.ingest``) is allowed in every
        mode, and that is not an inconsistency. Ingesting evidence enforces
        nothing and implies no control, so a credential for it claims nothing;
        refusing it would instead leave OBSERVED -- the mode whose whole
        content is "ACT sees this agent" -- with no way to be seen.
        """
        from app.bridge import capabilities as caps
        from app.bridge.modes import effective_mode, enforces_boundary_calls

        normalized = self._validate_scope(scope)
        governed = [e for e in normalized
                    if caps.CAPABILITIES[e["capability"]].plane == "GOVERNANCE"]
        if governed and not enforces_boundary_calls(agent):
            raise IdentityError(
                ErrorCode.EXTERNAL_MODE_DOES_NOT_ENFORCE,
                f"This agent's enforcement mode is {effective_mode(agent)!r}, which performs no "
                "enforcement at ACT's boundary, so a grant for the governed capability "
                f"{governed[0]['capability']!r} would imply control ACT does not have. Move the "
                "agent to GATEWAY_ENFORCED first, or scope this grant to evidence only "
                "(telemetry.ingest), which enforces nothing and is allowed in any mode.",
            )
        raw_secret = secrets.token_urlsafe(48)
        grant = ExternalCapabilityGrant(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            label=label,
            key_id=f"actx_{secrets.token_hex(16)}",
            secret_ciphertext=encrypt_secret(raw_secret),
            secret_hint=f"{raw_secret[:4]}...{raw_secret[-4:]}",
            scope=normalized,
            expires_at=expires_at,
            rate_limit_per_minute=rate_limit_per_minute,
            created_by=actor.id,
        )
        self.db.add(grant)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise IdentityError(ErrorCode.CONFLICT,
                                "A grant with this label already exists for this agent.") from exc
        # The audit records the key_id (an identifier) and the scope. It never
        # records the secret, its ciphertext or its hint.
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.EXTERNAL_GRANT_ISSUED,
            organization_id=agent.organization_id, actor_id=actor.id, identity_id=agent.id,
            meta={"grant_id": str(grant.id), "key_id": grant.key_id, "label": label,
                  "scope": normalized, "rate_limit_per_minute": rate_limit_per_minute,
                  "expires_at": expires_at.isoformat() if expires_at else None,
                  "enforcement_mode": effective_mode(agent)},
        )
        self.db.commit()
        self.db.refresh(grant)
        return grant, raw_secret

    @staticmethod
    def _validate_scope(scope: list[dict]) -> list[dict]:
        from app.bridge import capabilities as caps

        if not scope:
            raise IdentityError(ErrorCode.EXTERNAL_SCOPE_INVALID,
                                "A grant must name at least one capability; an empty scope "
                                "would be a credential that can do nothing.")
        normalized: list[dict] = []
        for entry in scope:
            key = (entry or {}).get("capability")
            spec = caps.get(key) if isinstance(key, str) else None
            if spec is None:
                raise IdentityError(
                    ErrorCode.EXTERNAL_CAPABILITY_UNKNOWN,
                    f"{key!r} is not a declared capability. ACT's boundary handles only "
                    f"{list(caps.CAPABILITIES)} -- it does not proxy arbitrary traffic.",
                )
            target = entry.get("target_ref")
            if spec.requires_target and target is None:
                raise IdentityError(
                    ErrorCode.EXTERNAL_SCOPE_INVALID,
                    f"Capability {key!r} must be scoped to a specific target; an unscoped "
                    "grant would reach every target of that capability.",
                )
            normalized.append({"capability": key,
                               "target_ref": str(target) if target is not None else None})
        return normalized

    def get_or_404(self, actor: User, grant_id: uuid.UUID) -> ExternalCapabilityGrant:
        grant = self.db.get(ExternalCapabilityGrant, grant_id)
        if grant is None or grant.organization_id != actor.organization_id:
            # 404 not 403: a cross-tenant probe must not learn the row exists.
            raise IdentityError(ErrorCode.EXTERNAL_GRANT_NOT_FOUND, "No such grant.")
        return grant

    def list_for_agent(self, actor: User, agent: Agent) -> list[ExternalCapabilityGrant]:
        return list(self.db.execute(
            select(ExternalCapabilityGrant).where(
                ExternalCapabilityGrant.organization_id == actor.organization_id,
                ExternalCapabilityGrant.agent_id == agent.id,
            ).order_by(ExternalCapabilityGrant.created_at.desc())
        ).scalars())

    def revoke(self, actor: User, grant_id: uuid.UUID, *,
               reason: str | None = None) -> ExternalCapabilityGrant:
        """Revoke immediately. Idempotent: revoking an already-revoked grant
        returns it unchanged rather than erroring, so a retried or concurrent
        revocation is never a failure an operator has to reason about.

        This is the one *real* enforcement reach GATEWAY_ENFORCED has beyond a
        single call: it ends the agent's ability to use ACT's boundary at all.
        It does not, and this module never claims it does, stop the agent.
        """
        grant = self.get_or_404(actor, grant_id)
        if grant.revoked_at is not None:
            return grant
        grant.revoked_at = _now()
        grant.revoked_by = actor.id
        grant.revocation_reason = reason
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.EXTERNAL_GRANT_REVOKED,
            organization_id=grant.organization_id, actor_id=actor.id,
            identity_id=grant.agent_id,
            meta={"grant_id": str(grant.id), "key_id": grant.key_id, "reason": reason},
        )
        self.db.commit()
        self.db.refresh(grant)
        return grant

    # ------------------------------------------------------------------ #
    # Verification (the boundary's front door)
    # ------------------------------------------------------------------ #
    def verify(self, *, key_id: str, timestamp: str, nonce: str, signature: str,
               method: str, path: str, body: bytes) -> ExternalIdentity:
        """Authenticate one signed request, or raise.

        Order matters and is deliberate: cheap structural checks first, the
        HMAC next, and the nonce write **last** -- a request that fails
        verification must not be able to consume a nonce, or an attacker could
        burn a legitimate caller's nonces with garbage signatures.
        """
        grant = self.db.execute(
            select(ExternalCapabilityGrant).where(ExternalCapabilityGrant.key_id == key_id)
        ).scalars().first()
        # One error for "no such key" and "bad signature": distinguishing them
        # tells an attacker which key_ids exist.
        if grant is None:
            raise IdentityError(ErrorCode.EXTERNAL_SIGNATURE_INVALID,
                                "Invalid credentials for this request.")
        now = _now()
        if grant.revoked_at is not None:
            raise IdentityError(ErrorCode.EXTERNAL_GRANT_REVOKED,
                                "This capability grant has been revoked.")
        if grant.expires_at is not None and grant.expires_at <= now:
            raise IdentityError(ErrorCode.EXTERNAL_GRANT_EXPIRED,
                                "This capability grant has expired.")

        try:
            sent_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise IdentityError(ErrorCode.EXTERNAL_SIGNATURE_INVALID,
                                "Invalid credentials for this request.") from exc
        if abs((now - sent_at).total_seconds()) > SIGNATURE_WINDOW_SECONDS:
            raise IdentityError(
                ErrorCode.EXTERNAL_SIGNATURE_EXPIRED,
                f"Request timestamp is outside the {SIGNATURE_WINDOW_SECONDS}s signing window.")
        if not nonce or len(nonce) > 128:
            raise IdentityError(ErrorCode.EXTERNAL_SIGNATURE_INVALID,
                                "Invalid credentials for this request.")

        expected = sign(decrypt_secret(grant.secret_ciphertext), method=method, path=path,
                        timestamp=timestamp, nonce=nonce, body=body)
        if not hmac.compare_digest(expected, signature or ""):
            raise IdentityError(ErrorCode.EXTERNAL_SIGNATURE_INVALID,
                                "Invalid credentials for this request.")

        self._consume_nonce(grant, nonce, now)

        agent = self.db.get(Agent, grant.agent_id)
        if agent is None or agent.organization_id != grant.organization_id:
            raise IdentityError(ErrorCode.EXTERNAL_SUBJECT_NOT_FOUND,
                                "The agent this grant names no longer exists.")
        return ExternalIdentity(grant=grant, agent=agent)

    def _consume_nonce(self, grant: ExternalCapabilityGrant, nonce: str,
                       now: datetime) -> None:
        """Record the nonce, committing immediately.

        The commit is the point: the unique constraint only decides a race
        between two *committed* inserts, so holding this open until the end of
        the request would let a replay run concurrently with the original. It
        also means a replay is rejected before any authorization work is done.
        """
        # Reap this grant's own expired nonces on the way past -- bounded work,
        # no cron, the same discipline `RateLimiter.check` uses for its bucket.
        self.db.execute(delete(ExternalRequestNonce).where(
            ExternalRequestNonce.grant_id == grant.id,
            ExternalRequestNonce.expires_at < now,
        ))
        self.db.add(ExternalRequestNonce(
            organization_id=grant.organization_id, grant_id=grant.id, nonce=nonce,
            expires_at=now + timedelta(seconds=SIGNATURE_WINDOW_SECONDS),
        ))
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.EXTERNAL_REPLAY_DETECTED,
                "This signed request has already been presented. Each request must carry a "
                "fresh nonce.",
            ) from exc


__all__ = [
    "SIGNATURE_WINDOW_SECONDS",
    "SIGNATURE_SCHEME",
    "HEADER_KEY_ID",
    "HEADER_TIMESTAMP",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "signing_string",
    "sign",
    "ExternalIdentity",
    "ExternalGrantService",
]
