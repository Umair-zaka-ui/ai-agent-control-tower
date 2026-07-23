"""Phase 5.2.4 SRS ACT-VER-FR-060..071 — portable attestation & DSSE signing.

Builds an in-toto Statement v1 predicate describing a published version,
wraps it in a DSSE envelope (``application/vnd.in-toto+json``), and signs
the DSSE Pre-Authentication Encoding (PAE) — not the raw payload — via the
configured ``SigningProvider``.

**Verification scope — internal only.** This phase deliberately builds no
public endpoint and no standalone verifier script (``ACT-VER-FR-070`` is
deferred — see ``docs/runtime/versioning.md``'s Known Deviations). The
in-toto/DSSE format is followed anyway: signed artifacts accumulate, and
the signature covers the document's *shape* — changing that shape later
means re-signing every version that already exists, while following a
documented external format now costs nothing and leaves the door open.

**Self-containment (a hard requirement)**: every claim in the predicate
must be interpretable from the document itself plus the public key — no
field may require a database lookup. Concretely, every identifier embedded
below is either an opaque UUID/string copied by value at build time (agent
id, version id, actor id, organization id) or a digest/timestamp — never a
foreign key that only resolves through this platform's schema.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentVersion,
    AgentVersionProvenance,
    AgentVersionSignature,
    AgentVersionSnapshot,
    AgentVersionStatusHistory,
    SigningKey,
)
from app.runtime.versioning import canonical
from app.runtime.versioning.keys import SigningKeyService
from app.runtime.versioning.signing.registry import get_signing_provider
from app.runtime.versioning.snapshot import checksum_of

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://ai-agent-control-tower.io/AgentVersionAttestation/v1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
SCHEMA_VERSION = "1.0"
BUILDER_ID = "ai-agent-control-tower"
BUILDER_VERSION = "5.2.4"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# DSSE Pre-Authentication Encoding — https://github.com/secure-systems-lab/dsse
# --------------------------------------------------------------------------- #
def pae(payload_type: str, payload: bytes) -> bytes:
    """``PAE(type, body) = "DSSEv1" SP LEN(type) SP type SP LEN(body) SP body``
    — what actually gets signed, per the DSSE spec exactly (signing the raw
    payload instead would break every external verifier that follows the
    spec)."""
    type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 " + str(len(type_bytes)).encode("ascii") + b" " + type_bytes + b" " + \
        str(len(payload)).encode("ascii") + b" " + payload


# --------------------------------------------------------------------------- #
# Manifest digest — what is actually signed (§6: "Order matters")
# --------------------------------------------------------------------------- #
def compute_manifest_digest(*, snapshot_digest: str, agent_id: uuid.UUID, version_id: uuid.UUID,
                           semantic_version: str, version_number: int, published_at: datetime) -> str:
    """A small, canonical manifest over the frozen snapshot's own digest
    plus enough version identity to make the manifest unambiguous —
    computed *after* the snapshot is frozen, over its digest, not the
    snapshot body again (already covered by ``snapshot_digest``)."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_digest": snapshot_digest,
        "agent_id": str(agent_id),
        "version_id": str(version_id),
        "semantic_version": semantic_version,
        "version_number": version_number,
        "published_at": published_at.isoformat(),
    }
    return canonical.digest(manifest)


# --------------------------------------------------------------------------- #
# In-toto Statement v1 predicate (§4.1)
# --------------------------------------------------------------------------- #
def build_attestation(agent: Agent, version: AgentVersion, *, snapshot_digest: str, publisher_id: uuid.UUID,
                      approvals: list[dict], correlation_id: str | None) -> dict:
    """Builds the in-toto Statement v1 document. Every value here is either
    copied by value from the version/agent rows or an opaque identifier —
    nothing is a lazily-resolved reference, satisfying the self-containment
    requirement above."""
    manifest_digest = version.manifest_digest or ""
    subject_digest_hex = manifest_digest.split(":", 1)[1] if ":" in manifest_digest else manifest_digest

    model_config = version.model_configuration or {}
    parameters_digest = canonical.digest(canonical.stringify_floats(model_config))
    prompt_digest = canonical.digest(canonical.stringify_floats(version.prompt_snapshot or {}))
    policy_digest = canonical.digest(canonical.stringify_floats(version.policy_snapshot or {}))
    tools = [{"name": tool_id, "digest": canonical.digest({"tool_id": tool_id})}
            for tool_id in (version.tools_snapshot or [])]

    return {
        "_type": STATEMENT_TYPE,
        "subject": [{
            # An opaque org identifier (not a "slug") keeps this fully
            # self-contained without an extra Organization lookup —
            # Organization.slug is nullable in this codebase, an id never is.
            "name": f"agent://{agent.organization_id}/{agent.slug}/versions/{version.semantic_version}",
            "digest": {"sha256": subject_digest_hex},  # bare hex, no "sha256:" prefix — in-toto convention
        }],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "agent": {"id": str(agent.id), "slug": agent.slug, "name": agent.name},
            "version": {
                "id": str(version.id), "semantic_version": version.semantic_version,
                "version_number": version.version, "status": version.status,
                "compatibility_level": version.compatibility_level,
            },
            "snapshot": {"digest": snapshot_digest, "algorithm": "canonical-sha256",
                        "schema_version": SCHEMA_VERSION},
            "configuration": {
                "model": {"provider": model_config.get("provider"), "model": model_config.get("model"),
                         "parameters_digest": parameters_digest},
                "prompt_digest": prompt_digest,
                "tools": tools,
                "capabilities": list(version.capabilities_snapshot or []),
                "policy_digest": policy_digest,
            },
            "provenance": {
                "published_by": {"id": str(publisher_id), "type": "USER"},
                "published_at": version.published_at.isoformat() if version.published_at else None,
                "approved_by": approvals,
                "source": {"repository": None, "commit": None, "ref": None},
                "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION},
                "correlation_id": correlation_id,
            },
            "attestation": {"created_at": _now().isoformat(), "format_version": SCHEMA_VERSION},
        },
    }


class AttestationService:
    """Builds, signs, verifies and countersigns attestations. Direct
    SQLAlchemy queries, no repository layer — matching the runtime domain
    convention (REPO_STATE §7)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _approvals(self, version: AgentVersion) -> list[dict]:
        if version.reviewed_by is None:
            return []
        approved_at = self.db.execute(
            select(AgentVersionStatusHistory.created_at).where(
                AgentVersionStatusHistory.agent_version_id == version.id,
                AgentVersionStatusHistory.new_status == "APPROVED",
            ).order_by(AgentVersionStatusHistory.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        return [{"id": str(version.reviewed_by), "at": approved_at.isoformat() if approved_at else None}]

    def build_and_sign(self, agent: Agent, version: AgentVersion, *, snapshot_digest: str,
                       publisher_id: uuid.UUID, correlation_id: str | None = None,
                       source_ip: str | None = None) -> AgentVersionSignature:
        """Called from ``publish()`` after the snapshot is frozen. Signing
        failure MUST propagate — this method never swallows an exception;
        unlike Phase 5.2.6's advisory compatibility analysis, an unsigned
        published version is an integrity hole (``ACT-VER-NFR-004``: fail
        closed)."""
        manifest_digest = compute_manifest_digest(
            snapshot_digest=snapshot_digest, agent_id=agent.id, version_id=version.id,
            semantic_version=version.semantic_version, version_number=version.version,
            published_at=version.published_at,
        )
        version.manifest_digest = manifest_digest

        document = build_attestation(agent, version, snapshot_digest=snapshot_digest,
                                     publisher_id=publisher_id, approvals=self._approvals(version),
                                     correlation_id=correlation_id)

        key_service = SigningKeyService(self.db)
        signing_key = key_service.ensure_key(settings.SIGNING_DEFAULT_KEY_ID)

        payload_bytes = canonical.canonicalize(document)
        provider = get_signing_provider()
        result = provider.sign(pae(PAYLOAD_TYPE, payload_bytes), signing_key.key_id)

        envelope = {
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "payloadType": PAYLOAD_TYPE,
            "signatures": [{"keyid": f"{signing_key.key_id}.v{result.key_version}",
                           "sig": base64.b64encode(result.signature).decode("ascii")}],
        }

        signature_row = AgentVersionSignature(
            agent_version_id=version.id, manifest_digest=manifest_digest, signature=result.signature,
            algorithm=result.algorithm, signing_key_id=signing_key.id, signing_key_version=result.key_version,
            signature_type="PUBLISHER", dsse_envelope=envelope, verification_status="VALID",
            signed_by=publisher_id,
        )
        self.db.add(signature_row)
        self.db.flush()

        version.signed_at = _now()
        # §5 — wire the pre-existing (previously always-null) signature_id
        # to this primary signature's id, rather than dropping the column;
        # see docs/runtime/versioning.md's Phase 5.2.4 section for why.
        version.signature_id = str(signature_row.id)

        provenance = AgentVersionProvenance(
            agent_version_id=version.id, actor_id=publisher_id, actor_type="USER",
            builder_identity=f"{BUILDER_ID}@{BUILDER_VERSION}", source_ip=source_ip,
            correlation_id=uuid.UUID(correlation_id) if correlation_id else None,
            attestation_document=document,
        )
        self.db.add(provenance)
        self.db.flush()
        return signature_row

    def countersign(self, version: AgentVersion, *, actor_id: uuid.UUID) -> AgentVersionSignature:
        """§7 ``POST .../countersign`` — adds an additional, independent
        signature over the same payload the ``PUBLISHER`` signature covers
        (``ACT-VER-FR-069``: multiple signatures per version permitted)."""
        publisher_signature = self.db.execute(
            select(AgentVersionSignature).where(
                AgentVersionSignature.agent_version_id == version.id,
                AgentVersionSignature.signature_type == "PUBLISHER",
            ).order_by(AgentVersionSignature.signed_at.desc()).limit(1)
        ).scalar_one_or_none()
        if publisher_signature is None:
            raise IdentityError(ErrorCode.SIGNATURE_MISSING,
                                "This version has not been signed yet — publish it first.")

        key_service = SigningKeyService(self.db)
        signing_key = key_service.ensure_key(settings.SIGNING_DEFAULT_KEY_ID)
        if signing_key.status == "REVOKED":
            raise IdentityError(ErrorCode.SIGNING_KEY_REVOKED, f"Signing key '{signing_key.key_id}' is revoked.")

        payload_bytes = base64.b64decode(publisher_signature.dsse_envelope["payload"])
        provider = get_signing_provider()
        result = provider.sign(pae(publisher_signature.dsse_envelope["payloadType"], payload_bytes),
                               signing_key.key_id)

        envelope = {
            "payload": publisher_signature.dsse_envelope["payload"],
            "payloadType": publisher_signature.dsse_envelope["payloadType"],
            "signatures": [{"keyid": f"{signing_key.key_id}.v{result.key_version}",
                           "sig": base64.b64encode(result.signature).decode("ascii")}],
        }

        signature_row = AgentVersionSignature(
            agent_version_id=version.id, manifest_digest=publisher_signature.manifest_digest,
            signature=result.signature, algorithm=result.algorithm, signing_key_id=signing_key.id,
            signing_key_version=result.key_version, signature_type="COUNTERSIGN", dsse_envelope=envelope,
            verification_status="VALID", signed_by=actor_id,
        )
        self.db.add(signature_row)
        self.db.commit()
        self.db.refresh(signature_row)
        return signature_row

    def verify(self, version: AgentVersion) -> dict:
        """``POST .../verify`` — independently re-verifies every signature
        row for this version, plus whether the frozen snapshot still
        matches what was signed. Never trusts the persisted
        ``verification_status`` alone; recomputes live."""
        signatures = list(self.db.execute(
            select(AgentVersionSignature).where(AgentVersionSignature.agent_version_id == version.id)
            .order_by(AgentVersionSignature.signed_at)
        ).scalars())
        if not signatures:
            raise IdentityError(ErrorCode.SIGNATURE_MISSING, "This version has not been signed.")

        provider = get_signing_provider()
        signature_checks = []
        for signature in signatures:
            envelope = signature.dsse_envelope
            payload_bytes = base64.b64decode(envelope["payload"])
            signing_key = self.db.get(SigningKey, signature.signing_key_id)
            try:
                signature_valid = provider.verify(pae(envelope["payloadType"], payload_bytes), signature.signature,
                                                  signing_key.key_id, signature.signing_key_version)
            except Exception:  # noqa: BLE001 — any provider error means "does not verify"
                signature_valid = False
            key_revoked = signing_key.status == "REVOKED"
            signature_checks.append({
                "signature_id": signature.id, "signature_type": signature.signature_type,
                "passed": signature_valid and not key_revoked,
                "signature_valid": signature_valid, "key_revoked": key_revoked,
            })

        # A tampered payload may not even be parseable JSON, or may lack the
        # expected shape entirely -- either case means "cannot confirm the
        # snapshot is intact," not a 500. The signature_valid check above
        # already independently catches this same tampering; this is a
        # second, orthogonal signal (someone could in principle tamper with
        # a *copy* of a validly-signed payload's snapshot digest field only).
        try:
            primary_payload = base64.b64decode(signatures[0].dsse_envelope["payload"])
            document = json.loads(primary_payload.decode("utf-8"))
            embedded_snapshot_digest = document["predicate"]["snapshot"]["digest"]
        except (ValueError, KeyError, TypeError):
            embedded_snapshot_digest = None

        live_snapshot = self.db.execute(
            select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == version.id)
        ).scalar_one_or_none()
        snapshot_intact = (embedded_snapshot_digest is not None and live_snapshot is not None
                          and checksum_of(live_snapshot.snapshot) == embedded_snapshot_digest)

        valid = snapshot_intact and all(check["passed"] for check in signature_checks)
        return {"version_id": version.id, "valid": valid, "snapshot_intact": snapshot_intact,
               "signatures": signature_checks}

    def get_attestation(self, version: AgentVersion) -> dict:
        """``GET .../attestation`` — returns the persisted in-toto Statement
        plus its DSSE envelope for the primary (``PUBLISHER``) signature."""
        signature = self.db.execute(
            select(AgentVersionSignature).where(
                AgentVersionSignature.agent_version_id == version.id,
                AgentVersionSignature.signature_type == "PUBLISHER",
            ).order_by(AgentVersionSignature.signed_at.desc()).limit(1)
        ).scalar_one_or_none()
        if signature is None:
            raise IdentityError(ErrorCode.ATTESTATION_UNAVAILABLE, "This version has not been signed yet.")
        payload_bytes = base64.b64decode(signature.dsse_envelope["payload"])
        return {"document": json.loads(payload_bytes.decode("utf-8")), "dsse_envelope": signature.dsse_envelope}

    def list_signatures(self, version_id: uuid.UUID) -> list[AgentVersionSignature]:
        return list(self.db.execute(
            select(AgentVersionSignature).where(AgentVersionSignature.agent_version_id == version_id)
            .order_by(AgentVersionSignature.signed_at)
        ).scalars())

    def get_provenance(self, version_id: uuid.UUID) -> AgentVersionProvenance | None:
        return self.db.execute(
            select(AgentVersionProvenance).where(AgentVersionProvenance.agent_version_id == version_id)
        ).scalar_one_or_none()
