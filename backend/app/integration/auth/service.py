"""Phase 2.1.2 SRS ACT-INT-FR-020..028 — ``ConnectorCredentialService``.

Follows the runtime domain's established pattern (``__init__(self, db:
Session)``, direct ORM queries, no repository layer) — the same
discipline ``ConnectorService`` (2.1.1) and ``ProviderCredentialService``
(5.7a.5) both already follow.

**Reuse, not reinvention** (the build prompt's own hard mandate):
encryption is ``app/runtime/providers/credential_crypto.py``'s
``encrypt_secret``/``decrypt_secret``/``mask_hint``, imported and called
directly — not copied, not re-implemented, not even wrapped. Those three
functions already operate on plain strings with no provider-specific
logic anywhere in them (they don't reference "provider" in any branch of
their own code, only in their module's docstring/settings names), so no
extraction or generalization was needed to reuse them here — the exact
same precedent Phase 5.6a.1's ``ToolCredentialService`` already set for
tool credentials. A connector credential bundle (possibly several
fields: api key; or client id/secret/token url; or cert/key) is
JSON-serialized into one string and that whole string is what
``encrypt_secret`` encrypts — the column never holds structured
plaintext (``ACT-INT-FR-025``, AC-09).

**Inherited Known Deviation** (not a new one — the build prompt is
explicit that none should be introduced): connector credentials share
the exact same platform-held Fernet key
(``settings.MODEL_CREDENTIAL_ENCRYPTION_KEY``/``_PATH``) that Phase
5.7a.5's provider credentials and Phase 5.6a.1's tool credentials already
use. The key necessarily enters process memory to encrypt/decrypt —
accepted pre-production, closes when Milestone 13 lands external
KMS/vault integration, exactly the closure condition 5.7a.5 (mirroring
5.2.4's own signing-key deviation) already recorded. See
``credential_crypto.py``'s own module docstring."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.integration.auth import registry as auth_registry
from app.integration.auth import token_manager
from app.integration.auth.base import OutboundRequest
from app.integration.errors import (
    ConnectorAuthSchemeUnsupportedError,
    ConnectorCredentialInvalidError,
    ConnectorCredentialNotFoundError,
)
from app.models.integration import Connector, ConnectorCredential, ConnectorInstance
from app.models.user import User
from app.runtime.providers.credential_crypto import decrypt_secret, encrypt_secret, mask_hint

_NO_AUTH_SCHEME = "NONE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorCredentialService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- lookups ----------------------------------------------------- #
    def _get_row(self, connector_instance_id: uuid.UUID, auth_scheme: str) -> ConnectorCredential | None:
        return self.db.execute(
            select(ConnectorCredential).where(
                ConnectorCredential.connector_instance_id == connector_instance_id,
                ConnectorCredential.auth_scheme == auth_scheme.upper(),
            )
        ).scalar_one_or_none()

    def _get_or_404(
        self, organization_id: uuid.UUID, connector_instance_id: uuid.UUID, auth_scheme: str,
    ) -> ConnectorCredential:
        row = self._get_row(connector_instance_id, auth_scheme)
        if row is None or row.organization_id != organization_id:
            raise ConnectorCredentialNotFoundError(connector_instance_id, auth_scheme.upper())
        return row

    def list_for_instance(self, organization_id: uuid.UUID, connector_instance_id: uuid.UUID) -> list[ConnectorCredential]:
        return list(self.db.execute(
            select(ConnectorCredential).where(
                ConnectorCredential.organization_id == organization_id,
                ConnectorCredential.connector_instance_id == connector_instance_id,
            ).order_by(ConnectorCredential.auth_scheme)
        ).scalars())

    def _decrypt_bundle(self, row: ConnectorCredential) -> dict[str, Any]:
        return json.loads(decrypt_secret(row.encrypted_secret))

    # --- store / delete / validate ------------------------------------ #
    def store(
        self, actor: User, organization_id: uuid.UUID, connector_instance_id: uuid.UUID,
        auth_scheme: str, credential: dict[str, Any],
    ) -> ConnectorCredential:
        """Upsert, keyed on ``(connector_instance_id, auth_scheme)`` —
        re-encrypts on replace (rotation, ``ACT-INT-FR-026``). An
        in-flight invocation that already called ``resolve_and_apply``
        holds its own plain, already-resolved credential value in memory
        (never a live reference back to this row), so it is structurally
        unaffected by a concurrent rotation; the next invocation resolves
        the new value. No mid-invocation re-resolution is attempted,
        mirroring 5.7a.5's rotation semantics exactly."""
        scheme = auth_registry.resolve(auth_scheme)  # raises ConnectorAuthSchemeUnsupportedError
        missing = [field for field in scheme.required_fields() if not credential.get(field)]
        if missing:
            raise ConnectorCredentialInvalidError(f"missing required field(s): {', '.join(missing)}")

        bundle_json = json.dumps(dict(credential), sort_keys=True)
        encrypted = encrypt_secret(bundle_json)
        primary_field = scheme.required_fields()[0]
        hint = mask_hint(str(credential[primary_field]))

        row = self._get_row(connector_instance_id, auth_scheme)
        if row is None:
            row = ConnectorCredential(
                connector_instance_id=connector_instance_id, organization_id=organization_id,
                auth_scheme=auth_scheme.upper(), encrypted_secret=encrypted, secret_hint=hint,
                status="ACTIVE", created_by=actor.id,
            )
            self.db.add(row)
        else:
            row.encrypted_secret = encrypted
            row.secret_hint = hint
            row.status = "ACTIVE"
            row.last_validated_at = None
            row.validation_status = None
        self.db.flush()
        # ACT-INT-FR-025 -- meta carries the scheme identifier only, never
        # the credential value or its ciphertext.
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED,
            organization_id=organization_id, actor_id=actor.id,
            meta={"connector_instance_id": str(connector_instance_id), "auth_scheme": auth_scheme.upper()},
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(
        self, actor: User, organization_id: uuid.UUID, connector_instance_id: uuid.UUID, auth_scheme: str,
    ) -> None:
        row = self._get_or_404(organization_id, connector_instance_id, auth_scheme)
        self.db.delete(row)
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.INTEGRATION_CONNECTOR_CREDENTIAL_DELETED,
            organization_id=organization_id, actor_id=actor.id,
            meta={"connector_instance_id": str(connector_instance_id), "auth_scheme": auth_scheme.upper()},
        )
        self.db.commit()

    def validate(
        self, actor: User, organization_id: uuid.UUID, connector_instance_id: uuid.UUID, auth_scheme: str,
        *, transport=None,
    ) -> dict[str, Any]:
        """``ACT-INT-FR-028`` — records ``last_validated_at``/
        ``validation_status`` without ever returning the credential
        itself. For an OAuth2 scheme this is a real token
        acquisition/refresh attempt against the configured token
        endpoint (``token_manager``); for every other scheme, since
        there is no real connector to call yet this sub-phase (that's
        2.2.x), validation is a declared structural check — every
        required field is present and the stored bundle decrypts
        cleanly — exactly as the build prompt's own §7 describes."""
        row = self._get_or_404(organization_id, connector_instance_id, auth_scheme)
        scheme_id = auth_scheme.upper()
        bundle = self._decrypt_bundle(row)

        if scheme_id in auth_registry.OAUTH2_SCHEME_IDENTIFIERS:
            try:
                token_manager.get_valid_access_token(
                    self.db, connector_instance_id, organization_id, scheme=scheme_id, config=bundle,
                    transport=transport,
                )
                validation_status, message = "VALID", "Token acquisition succeeded."
            except Exception as exc:  # noqa: BLE001 -- any failure is a validation failure, never a 500
                validation_status, message = "INVALID", str(exc)
        else:
            scheme = auth_registry.resolve(scheme_id)
            missing = [field for field in scheme.required_fields() if not bundle.get(field)]
            if missing:
                validation_status, message = "INVALID", f"missing required field(s): {', '.join(missing)}"
            else:
                validation_status, message = "VALID", "Declared fields present and the stored bundle decrypts cleanly."

        row.last_validated_at = _now()
        row.validation_status = validation_status
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.INTEGRATION_CONNECTOR_CREDENTIAL_VALIDATED,
            organization_id=organization_id, actor_id=actor.id,
            meta={"connector_instance_id": str(connector_instance_id), "auth_scheme": scheme_id,
                  "validation_status": validation_status},
        )
        self.db.commit()
        self.db.refresh(row)
        return {"success": validation_status == "VALID", "validation_status": validation_status, "message": message}

    # --- resolution & application -------------------------------------- #
    def resolve_and_apply(
        self, connector_instance: ConnectorInstance, request: OutboundRequest, *, transport=None,
    ) -> OutboundRequest:
        """The proof this framework actually works end to end (against a
        fixture request, per the build prompt — no real connector
        invokes yet). Reads the connector *type*'s declared
        ``auth_requirements.scheme`` (2.1.1), resolves the matching
        stored credential, and — for the two OAuth2 schemes only —
        obtains a valid access token via ``token_manager`` first,
        merging it into the credential mapping before the scheme ever
        sees it (``ACT-INT-FR-023``: a credential is resolved at
        invocation time, never a step earlier)."""
        type_row = self.db.get(Connector, connector_instance.connector_id)
        scheme_id = (type_row.auth_requirements or {}).get("scheme", _NO_AUTH_SCHEME)
        if scheme_id == _NO_AUTH_SCHEME:
            return request

        row = self._get_row(connector_instance.id, scheme_id)
        if row is None:
            raise ConnectorCredentialNotFoundError(connector_instance.id, scheme_id)

        scheme = auth_registry.resolve(scheme_id)
        bundle = self._decrypt_bundle(row)
        if scheme_id in auth_registry.OAUTH2_SCHEME_IDENTIFIERS:
            access_token = token_manager.get_valid_access_token(
                self.db, connector_instance.id, connector_instance.organization_id,
                scheme=scheme_id, config=bundle, transport=transport,
            )
            bundle = {**bundle, "access_token": access_token}
        return scheme.apply(request, bundle)

    # --- OAuth2 authorization-code: URL + callback ---------------------- #
    def build_authorization_url(self, connector_instance: ConnectorInstance, *, state: str) -> str:
        """Returns the URL a browser would be redirected to for consent —
        construction only. Nothing in this backend performs that
        redirect; see ``schemes/oauth2_authorization_code.py``'s "built
        vs stubbed" note."""
        from urllib.parse import urlencode

        type_row = self.db.get(Connector, connector_instance.connector_id)
        scheme_id = (type_row.auth_requirements or {}).get("scheme")
        if scheme_id != "OAUTH2_AUTHORIZATION_CODE":
            raise ConnectorAuthSchemeUnsupportedError(scheme_id or _NO_AUTH_SCHEME)
        row = self._get_or_404(connector_instance.organization_id, connector_instance.id, scheme_id)
        bundle = self._decrypt_bundle(row)
        query = urlencode({
            "response_type": "code", "client_id": bundle["client_id"],
            "redirect_uri": bundle["redirect_uri"], "state": state,
        })
        return f"{bundle['authorize_url']}?{query}"

    def complete_authorization_code_exchange(
        self, connector_instance: ConnectorInstance, *, code: str, transport=None,
    ) -> None:
        """The callback endpoint's entry point — exchanges ``code`` for a
        token pair and persists it via ``token_manager``. Built, not
        stubbed (see the scheme module's docstring)."""
        type_row = self.db.get(Connector, connector_instance.connector_id)
        scheme_id = (type_row.auth_requirements or {}).get("scheme")
        if scheme_id != "OAUTH2_AUTHORIZATION_CODE":
            raise ConnectorAuthSchemeUnsupportedError(scheme_id or _NO_AUTH_SCHEME)
        row = self._get_or_404(connector_instance.organization_id, connector_instance.id, scheme_id)
        bundle = self._decrypt_bundle(row)
        token_manager.store_authorization_code_exchange(
            self.db, connector_instance.id, connector_instance.organization_id,
            token_url=bundle["token_url"], client_id=bundle["client_id"], client_secret=bundle["client_secret"],
            code=code, redirect_uri=bundle["redirect_uri"], transport=transport,
        )
