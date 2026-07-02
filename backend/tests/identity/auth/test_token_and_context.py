"""Unit tests: IdentityContext, TokenService, CredentialService (no DB)."""

from __future__ import annotations

import time

import pytest

from app.core.security import hash_password
from app.identity.auth.context import IdentityContext
from app.identity.auth.credential_service import CredentialService
from app.identity.auth.enums import AuthMethod
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError


def _ctx() -> IdentityContext:
    return IdentityContext(
        identity_id="user_1",
        identity_type="HUMAN_USER",
        auth_method=AuthMethod.PASSWORD.value,
        organization_id="org_1",
        roles=["ROLE_ADMIN"],
        permissions=["agent.view", "policy.create"],
        session_id="sess_1",
    )


def test_identity_context_predicates() -> None:
    ctx = _ctx()
    assert ctx.has_permission("agent.view")
    assert ctx.has_role("ROLE_ADMIN")
    assert not ctx.is_machine()
    assert IdentityContext(identity_id="a", identity_type="AI_AGENT", auth_method="API_KEY").is_machine()


def test_access_token_claims_round_trip() -> None:
    svc = TokenService()
    token = svc.create_access_token(_ctx())
    claims = svc.validate_access_token(token)
    for key in ("sub", "identity_id", "identity_type", "organization_id", "roles",
                "permissions", "session_id", "iss", "aud", "iat", "exp", "jti", "token_type"):
        assert key in claims
    assert claims["identity_type"] == "HUMAN_USER"
    assert claims["token_type"] == "access"


def test_expired_token_rejected() -> None:
    svc = TokenService()
    token = svc.create_access_token(_ctx(), ttl_seconds=1)
    time.sleep(2)
    with pytest.raises(IdentityError) as exc:
        svc.validate_access_token(token)
    assert exc.value.code == ErrorCode.TOKEN_EXPIRED


def test_tampered_token_rejected() -> None:
    svc = TokenService()
    token = svc.create_access_token(_ctx())
    with pytest.raises(IdentityError) as exc:
        svc.validate_access_token(token + "x")
    assert exc.value.code in (ErrorCode.INVALID_CREDENTIALS, ErrorCode.TOKEN_EXPIRED)


def test_resolver_from_claims() -> None:
    svc = TokenService()
    claims = svc.validate_access_token(svc.create_access_token(_ctx()))
    ctx = IdentityContextResolver.from_claims(claims)
    assert ctx.identity_id == "user_1"
    assert "agent.view" in ctx.permissions


def test_credential_service() -> None:
    h = hash_password("Str0ngPass")
    assert CredentialService.verify_password("Str0ngPass", h)
    assert not CredentialService.verify_password("wrong", h)
    assert CredentialService.is_active("ACTIVE")
    assert not CredentialService.is_active("SUSPENDED")
    assert CredentialService.is_expired(None) is False
