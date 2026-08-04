"""Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 token acquisition, caching and
concurrency-safe refresh.

**Concurrency approach (row-level lock, documented per the build
prompt's explicit ask)**: ``get_valid_access_token`` takes out a
``SELECT ... FOR UPDATE`` on the *parent* ``connector_instances`` row —
not the ``connector_oauth_tokens`` row itself. Locking the token row
directly cannot serialize the very first acquisition (no row exists yet
to lock, so two concurrent first-callers would both pass a "does a row
exist" check and race to ``INSERT``, one losing to the unique
constraint). The parent instance row always exists by the time this
function is ever called, so locking it is both semantically apt ("only
one thread may mutate this connector's credentials at a time" ) and
correct for the create-or-refresh case uniformly. The lock is held only
for the duration of the check-then-refresh-then-commit — committing
(whether or not a refresh actually happened) releases it immediately, so
a second, concurrently-blocked caller re-checks expiry against the
now-current row and, finding it valid, returns the already-refreshed
token instead of refreshing a second time. This is the same
"``SELECT ... FOR UPDATE`` as the serialization point" discipline
``ExecutionWorkerService.claim_next`` already established elsewhere in
this codebase — see ``test_oauth_concurrent_refresh_does_not_double_refresh``
for the real-thread, real-Postgres proof.

No real network call is ever made in this codebase's own tests — every
token-endpoint call accepts an injectable ``httpx.BaseTransport`` fixture,
mirroring ``tests/runtime/conftest.py``'s ``replay_transport`` pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integration.errors import ConnectorOAuthRefreshFailedError
from app.models.integration import ConnectorInstance, ConnectorOAuthToken
from app.runtime.providers.credential_crypto import decrypt_secret, encrypt_secret

# A token within this many seconds of expiry is treated as already
# expired -- avoids a call that acquires a token and then immediately
# races its own expiry before the outbound request it's for even sends.
REFRESH_MARGIN_SECONDS = 60
_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int


def _post_token_request(
    token_url: str, data: dict[str, str], *, transport: httpx.BaseTransport | None = None,
) -> TokenResponse:
    client_kwargs: dict = {"timeout": _DEFAULT_TIMEOUT_SECONDS}
    if transport is not None:
        client_kwargs["transport"] = transport
    try:
        with httpx.Client(**client_kwargs) as client:
            response = client.post(token_url, data=data)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise ConnectorOAuthRefreshFailedError(str(exc)) from exc
    try:
        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in", 3600)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectorOAuthRefreshFailedError(f"malformed token response: {exc}") from exc


def exchange_client_credentials(
    token_url: str, client_id: str, client_secret: str, *, transport: httpx.BaseTransport | None = None,
) -> TokenResponse:
    return _post_token_request(
        token_url,
        {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        transport=transport,
    )


def exchange_authorization_code(
    token_url: str, client_id: str, client_secret: str, code: str, redirect_uri: str, *,
    transport: httpx.BaseTransport | None = None,
) -> TokenResponse:
    return _post_token_request(
        token_url,
        {"grant_type": "authorization_code", "client_id": client_id, "client_secret": client_secret,
         "code": code, "redirect_uri": redirect_uri},
        transport=transport,
    )


def refresh_with_token(
    token_url: str, client_id: str, client_secret: str, refresh_token: str, *,
    transport: httpx.BaseTransport | None = None,
) -> TokenResponse:
    return _post_token_request(
        token_url,
        {"grant_type": "refresh_token", "client_id": client_id, "client_secret": client_secret,
         "refresh_token": refresh_token},
        transport=transport,
    )


def _store_token_response(
    db: Session, connector_instance_id: uuid.UUID, organization_id: uuid.UUID, token: TokenResponse,
    *, existing: ConnectorOAuthToken | None,
) -> ConnectorOAuthToken:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.expires_in)
    encrypted_access = encrypt_secret(token.access_token)
    encrypted_refresh = (
        encrypt_secret(token.refresh_token) if token.refresh_token
        else (existing.encrypted_refresh_token if existing is not None else None)
    )
    if existing is None:
        row = ConnectorOAuthToken(
            connector_instance_id=connector_instance_id, organization_id=organization_id,
            encrypted_access_token=encrypted_access, encrypted_refresh_token=encrypted_refresh,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row = existing
        row.encrypted_access_token = encrypted_access
        row.encrypted_refresh_token = encrypted_refresh
        row.expires_at = expires_at
    return row


def store_authorization_code_exchange(
    db: Session, connector_instance_id: uuid.UUID, organization_id: uuid.UUID,
    *, token_url: str, client_id: str, client_secret: str, code: str, redirect_uri: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """The ``oauth/callback`` endpoint's entry point — completes the
    authorization-code exchange and persists the resulting access +
    refresh token pair. Locks the parent instance row for the same
    reason ``get_valid_access_token`` does (see module docstring)."""
    db.execute(select(ConnectorInstance.id).where(ConnectorInstance.id == connector_instance_id).with_for_update())
    existing = db.execute(
        select(ConnectorOAuthToken).where(ConnectorOAuthToken.connector_instance_id == connector_instance_id)
    ).scalar_one_or_none()
    token = exchange_authorization_code(token_url, client_id, client_secret, code, redirect_uri, transport=transport)
    _store_token_response(db, connector_instance_id, organization_id, token, existing=existing)
    db.commit()


def get_valid_access_token(
    db: Session, connector_instance_id: uuid.UUID, organization_id: uuid.UUID, *,
    scheme: str, config: dict, transport: httpx.BaseTransport | None = None,
) -> str:
    """Returns a valid, non-expired access token for this instance,
    refreshing (or, for client-credentials, acquiring for the first
    time) if needed — a caller of this function never presents an
    expired token (``ACT-INT-FR-024``). See the module docstring for the
    concurrency-safety argument."""
    db.execute(select(ConnectorInstance.id).where(ConnectorInstance.id == connector_instance_id).with_for_update())

    row = db.execute(
        select(ConnectorOAuthToken).where(ConnectorOAuthToken.connector_instance_id == connector_instance_id)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is not None and row.expires_at > now + timedelta(seconds=REFRESH_MARGIN_SECONDS):
        db.commit()  # releases the instance-row lock; nothing changed
        return decrypt_secret(row.encrypted_access_token)

    if row is not None and row.encrypted_refresh_token:
        token = refresh_with_token(
            config["token_url"], config["client_id"], config["client_secret"],
            decrypt_secret(row.encrypted_refresh_token), transport=transport,
        )
    elif scheme == "OAUTH2_CLIENT_CREDENTIALS":
        token = exchange_client_credentials(
            config["token_url"], config["client_id"], config["client_secret"], transport=transport,
        )
    else:
        db.rollback()
        raise ConnectorOAuthRefreshFailedError(
            "no cached refresh token, and the authorization-code scheme cannot self-acquire one -- "
            "complete the code exchange via the oauth/callback endpoint first."
        )

    _store_token_response(db, connector_instance_id, organization_id, token, existing=row)
    db.commit()
    return token.access_token
