"""Phase 2.3.1 SRS ACT-INT-FR-180..187 — ``FederationService``: the
orchestration layer for OIDC/SAML login and per-organization federation
configuration.

**The inversion, applied.** Every prior connector sub-phase (2.1.2, 2.2.x)
authenticated the *platform to* an external system, holding a platform
secret and presenting it outward. This service runs the opposite
direction: it verifies a signed assertion *from* an external IdP and never
receives, or stores, the user's own credential at all (``ACT-INT-FR-186``)
— only the already-verified claims a successful ``oidc.verify_id_token``/
``saml.verify_response`` call produced.

**Federation terminates in the existing session issuance — never a
parallel one (``ACT-INT-FR-182``).** ``_issue_session`` below calls the
exact same ``SessionLifecycleService``/``RefreshRotationService``/
``IdentityContextResolver``/``TokenService`` quartet
``AuthenticationService.login`` calls for a local password login, just
substituting the credential-verification step (a password check) with an
already-verified assertion, and recording ``login_method=AuthMethod.OIDC``/
``AuthMethod.SAML`` instead of ``PASSWORD``. After that call returns, a
federated session is indistinguishable from a local one to every other
part of this platform — RBAC, ABAC, audit, session listing, force-logout,
all of it.

**Assurance level is deliberately AAL1, never speculatively AAL2.** The
IdP may have required MFA before issuing its assertion, but this platform
has no reliable way to introspect that, and the whole point of federation
is that the enterprise's own IdP owns that decision (see this phase's own
build prompt §3, "the IdP owns MFA"). Claiming AAL2 without being able to
verify it would be asserting something this platform cannot actually
stand behind — AAL1 (single verified factor, from this platform's own
point of view) is the honest, conservative default, exactly matching
local password login's own posture.

**CSRF/replay defense without a new "pending requests" table.** Both
flows generate a short-lived, platform-signed flow token (reusing the
existing ``settings.JWT_SECRET_KEY``/``JWT_ALGORITHM`` — no new secret) —
OIDC's own ``state`` parameter, SAML's own ``RelayState`` — carrying
whatever this login attempt needs to verify itself at the callback
(the nonce, for OIDC; the AuthnRequest id, for SAML) plus a ``purpose``
tag and a short expiry. Forging one requires the platform's own signing
key; replaying an old one past its expiry, or across protocols, fails the
signature/purpose check before anything else runs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from jose import jwt as jose_jwt
from jose.exceptions import JOSEError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.context import IdentityContext
from app.identity.auth.enums import AuthAssuranceLevel, AuthMethod
from app.identity.auth.refresh_rotation_service import RefreshRotationService
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.session_lifecycle_service import SessionLifecycleService
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.federation import claim_mapping, oidc, saml
from app.identity.federation.oidc import OidcVerificationError
from app.identity.federation.saml import SamlVerificationError
from app.identity.models.enums import IdentityStatus
from app.identity.models.federation import FederatedIdentity, FederationConfig
from app.identity.registration.provisioning_service import ProvisionRequest, UserProvisioningService
from app.identity.roles.engine import RoleEngine
from app.models.rbac import Role
from app.models.user import User
from app.runtime.providers.credential_crypto import decrypt_secret, encrypt_secret

_OIDC_STATE_PURPOSE = "oidc_state"
_SAML_RELAY_STATE_PURPOSE = "saml_relay_state"
_FLOW_TOKEN_TTL_SECONDS = 600  # 10 minutes -- long enough for a real IdP round trip


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class FederatedLoginResult:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    context: IdentityContext
    is_new_user: bool


class FederationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Configuration (ACT-INT-FR-185 — per organization)
    # ------------------------------------------------------------------ #
    def create_config(
        self, actor: User, organization_id: uuid.UUID, *, protocol: str, provider_type: str, display_name: str,
        configuration: Mapping[str, Any], client_secret: str | None = None,
        jit_provisioning_enabled: bool = False, claim_mappings: Mapping[str, Any] | None = None,
        default_role_id: uuid.UUID | None = None,
    ) -> FederationConfig:
        _validate_protocol_configuration(protocol, configuration)
        config = FederationConfig(
            organization_id=organization_id, protocol=protocol, provider_type=provider_type,
            display_name=display_name, configuration=dict(configuration),
            encrypted_client_secret=encrypt_secret(client_secret) if client_secret else None,
            jit_provisioning_enabled=jit_provisioning_enabled,
            claim_mappings=dict(claim_mappings or {"rules": []}),
            default_role_id=default_role_id, status="ACTIVE", created_by=actor.id,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def get_config(self, organization_id: uuid.UUID, config_id: uuid.UUID) -> FederationConfig:
        config = self.db.get(FederationConfig, config_id)
        if config is None or config.organization_id != organization_id:
            raise IdentityError(ErrorCode.FEDERATION_CONFIG_NOT_FOUND, "Federation configuration does not exist.")
        return config

    def list_configs(self, organization_id: uuid.UUID) -> list[FederationConfig]:
        return list(self.db.execute(
            select(FederationConfig).where(FederationConfig.organization_id == organization_id)
            .order_by(FederationConfig.created_at)
        ).scalars())

    def update_config(
        self, organization_id: uuid.UUID, config_id: uuid.UUID, **fields: Any,
    ) -> FederationConfig:
        config = self.get_config(organization_id, config_id)
        client_secret = fields.pop("client_secret", None)
        if client_secret is not None:
            config.encrypted_client_secret = encrypt_secret(client_secret) if client_secret else None
        if "configuration" in fields and fields["configuration"] is not None:
            _validate_protocol_configuration(config.protocol, fields["configuration"])
        for key in ("display_name", "configuration", "jit_provisioning_enabled", "claim_mappings",
                    "default_role_id", "status"):
            if key in fields and fields[key] is not None:
                setattr(config, key, fields[key])
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_config(self, organization_id: uuid.UUID, config_id: uuid.UUID) -> None:
        config = self.get_config(organization_id, config_id)
        self.db.delete(config)
        self.db.commit()

    def test_config(self, organization_id: uuid.UUID, config_id: uuid.UUID) -> dict[str, Any]:
        """A lightweight, side-effect-free reachability/shape check —
        never authenticates, never touches a user credential. OIDC: the
        discovery document and JWKS are fetched (proving the endpoints
        are real and reachable). SAML: the settings dict is validated
        structurally by the toolkit itself (catches a malformed
        certificate or missing required field)."""
        config = self.get_config(organization_id, config_id)
        try:
            if config.protocol == "OIDC":
                cfg = config.configuration
                discovery = oidc.fetch_discovery_document(cfg["issuer"]) if cfg.get("use_discovery") else cfg
                jwks_uri = discovery.get("jwks_uri") or cfg.get("jwks_uri")
                oidc.fetch_jwks(jwks_uri)
                return {"success": True, "message": "Discovery document and JWKS retrieved successfully."}
            else:
                from onelogin.saml2.settings import OneLogin_Saml2_Settings

                settings_dict = saml.build_settings(config.configuration)
                errors = OneLogin_Saml2_Settings(settings_dict, sp_validation_only=True).check_settings(settings_dict)
                if errors:
                    return {"success": False, "message": f"Invalid SAML settings: {'; '.join(errors)}"}
                return {"success": True, "message": "SAML settings are structurally valid."}
        except OidcVerificationError as exc:
            return {"success": False, "message": str(exc)}

    # ------------------------------------------------------------------ #
    # OIDC — initiate (ACT-INT-FR-180)
    # ------------------------------------------------------------------ #
    def start_oidc_login(self, organization_id: uuid.UUID, config_id: uuid.UUID, *, redirect_uri: str) -> str:
        config = self._active_config(organization_id, config_id, protocol="OIDC")
        cfg = config.configuration
        state, nonce = oidc.generate_state_nonce()
        flow_token = self._sign_flow_token({
            "purpose": _OIDC_STATE_PURPOSE, "organization_id": str(organization_id),
            "federation_config_id": str(config_id), "nonce": nonce,
        })
        return oidc.build_authorization_url(
            cfg["authorization_endpoint"], client_id=cfg["client_id"], redirect_uri=redirect_uri,
            state=flow_token, nonce=nonce,
        )

    def handle_oidc_callback_by_state(
        self, organization_id: uuid.UUID, *, code: str, state: str, redirect_uri: str,
        ip_address: str | None = None, user_agent: str | None = None, request_id: str | None = None,
    ) -> FederatedLoginResult:
        """The route-facing entry point: ``config_id`` is not part of the
        callback URL at all — it is recovered from the verified ``state``
        token itself (see module docstring). Peeking it requires verifying
        the token once here and, redundantly but harmlessly, again inside
        ``handle_oidc_callback`` below — verification has no side effects,
        so the small duplication is a simplicity/safety tradeoff, not a
        correctness one."""
        flow_claims = self._verify_flow_token(state, purpose=_OIDC_STATE_PURPOSE)
        if flow_claims.get("organization_id") != str(organization_id):
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "State does not match this organization.")
        config_id = uuid.UUID(flow_claims["federation_config_id"])
        return self.handle_oidc_callback(
            organization_id, config_id, code=code, state=state, redirect_uri=redirect_uri,
            ip_address=ip_address, user_agent=user_agent, request_id=request_id,
        )

    def handle_oidc_callback(
        self, organization_id: uuid.UUID, config_id: uuid.UUID, *, code: str, state: str, redirect_uri: str,
        ip_address: str | None = None, user_agent: str | None = None, request_id: str | None = None,
    ) -> FederatedLoginResult:
        flow_claims = self._verify_flow_token(state, purpose=_OIDC_STATE_PURPOSE)
        if flow_claims.get("organization_id") != str(organization_id) or flow_claims.get("federation_config_id") != str(config_id):
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "State does not match this login attempt.")

        config = self._active_config(organization_id, config_id, protocol="OIDC")
        cfg = config.configuration
        client_secret = decrypt_secret(config.encrypted_client_secret) if config.encrypted_client_secret else None

        try:
            id_token = oidc.exchange_code_for_id_token(
                cfg["token_endpoint"], code=code, client_id=cfg["client_id"], client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            jwks = oidc.fetch_jwks(cfg["jwks_uri"])
            claims = oidc.verify_id_token(
                id_token, jwks, issuer=cfg["issuer"], audience=cfg["client_id"], nonce=flow_claims["nonce"],
                algorithms=cfg.get("algorithms", ["RS256"]),
            )
        except OidcVerificationError as exc:
            raise IdentityError(ErrorCode.FEDERATION_ASSERTION_INVALID, "OIDC assertion could not be verified.") from exc

        user, is_new = self._resolve_or_provision_user(
            config, subject=claims.subject, email=claims.email, name=claims.name, groups=list(claims.groups),
        )
        return self._issue_session(
            user, login_method=AuthMethod.OIDC.value, is_new_user=is_new,
            ip_address=ip_address, user_agent=user_agent, request_id=request_id,
        )

    # ------------------------------------------------------------------ #
    # SAML — initiate (ACT-INT-FR-180)
    # ------------------------------------------------------------------ #
    def start_saml_login(self, organization_id: uuid.UUID, config_id: uuid.UUID) -> str:
        config = self._active_config(organization_id, config_id, protocol="SAML")
        settings_dict = saml.build_settings(config.configuration)
        request_id, saml_request = saml.build_authn_request(settings_dict)
        relay_state = self._sign_flow_token({
            "purpose": _SAML_RELAY_STATE_PURPOSE, "organization_id": str(organization_id),
            "federation_config_id": str(config_id), "request_id": request_id,
        })
        return saml.build_redirect_url(config.configuration["idp_sso_url"], saml_request, relay_state)

    def handle_saml_acs_by_relay_state(
        self, organization_id: uuid.UUID, *, saml_response: str, relay_state: str, request: Any,
        ip_address: str | None = None, user_agent: str | None = None, request_id: str | None = None,
    ) -> FederatedLoginResult:
        """The route-facing entry point, mirroring
        ``handle_oidc_callback_by_state`` exactly: ``config_id`` is
        recovered from the verified ``RelayState`` token itself. ``request``
        is the framework's own request object (a FastAPI ``Request``) —
        this is the one place this module touches web-framework concerns,
        kept minimal and only to build the ``python3-saml`` "request data"
        shape ``saml.build_request_data`` expects."""
        flow_claims = self._verify_flow_token(relay_state, purpose=_SAML_RELAY_STATE_PURPOSE)
        if flow_claims.get("organization_id") != str(organization_id):
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "RelayState does not match this organization.")
        config_id = uuid.UUID(flow_claims["federation_config_id"])
        request_data = saml.build_request_data(
            https=request.url.scheme == "https", http_host=request.url.hostname or "",
            script_name=request.url.path, post_data={"SAMLResponse": saml_response, "RelayState": relay_state},
        )
        return self.handle_saml_acs(
            organization_id, config_id, request_data=request_data, relay_state=relay_state,
            ip_address=ip_address, user_agent=user_agent, request_id=request_id,
        )

    def handle_saml_acs(
        self, organization_id: uuid.UUID, config_id: uuid.UUID, *, request_data: Mapping[str, Any], relay_state: str,
        ip_address: str | None = None, user_agent: str | None = None, request_id: str | None = None,
    ) -> FederatedLoginResult:
        flow_claims = self._verify_flow_token(relay_state, purpose=_SAML_RELAY_STATE_PURPOSE)
        if flow_claims.get("organization_id") != str(organization_id) or flow_claims.get("federation_config_id") != str(config_id):
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "RelayState does not match this login attempt.")

        config = self._active_config(organization_id, config_id, protocol="SAML")
        settings_dict = saml.build_settings(config.configuration)
        try:
            claims = saml.verify_response(settings_dict, request_data, expected_request_id=flow_claims["request_id"])
        except SamlVerificationError as exc:
            raise IdentityError(ErrorCode.FEDERATION_ASSERTION_INVALID, "SAML assertion could not be verified.") from exc

        cfg = config.configuration
        email = _first_attribute(claims.attributes, cfg.get("email_attribute", "email"))
        name = _first_attribute(claims.attributes, cfg.get("name_attribute", "name"))
        groups = claims.attributes.get(cfg.get("group_attribute", "groups"), [])

        user, is_new = self._resolve_or_provision_user(
            config, subject=claims.subject, email=email, name=name, groups=list(groups),
        )
        return self._issue_session(
            user, login_method=AuthMethod.SAML.value, is_new_user=is_new,
            ip_address=ip_address, user_agent=user_agent, request_id=request_id,
        )

    def sp_metadata(self, organization_id: uuid.UUID, config_id: uuid.UUID) -> str:
        config = self._active_config(organization_id, config_id, protocol="SAML")
        return saml.sp_metadata_xml(saml.build_settings(config.configuration))

    # ------------------------------------------------------------------ #
    # Mapping to the existing user/RBAC model (ACT-INT-FR-182, FR-183, FR-184)
    # ------------------------------------------------------------------ #
    def _resolve_or_provision_user(
        self, config: FederationConfig, *, subject: str, email: str | None, name: str | None, groups: list[str],
    ) -> tuple[User, bool]:
        link = self.db.execute(
            select(FederatedIdentity).where(
                FederatedIdentity.federation_config_id == config.id,
                FederatedIdentity.external_subject_id == subject,
            )
        ).scalar_one_or_none()
        if link is not None:
            user = self.db.get(User, link.user_id)
            if user is None:
                raise IdentityError(
                    ErrorCode.FEDERATION_ASSERTION_INVALID, "The platform account for this identity no longer exists.",
                )
            link.last_federated_login_at = _now()
            self.db.commit()
            return user, False

        if not email:
            raise IdentityError(
                ErrorCode.FEDERATION_CLAIM_MAPPING_FAILED, "The IdP assertion carried no email claim.",
            )
        normalized_email = email.strip().lower()

        # Linking to an EXISTING local account by email is always permitted
        # (no new identity is created here — only a mapping is established),
        # regardless of jit_provisioning_enabled, which gates NEW user
        # creation only, below. This is the common real-world case: an org
        # provisions accounts first, then turns federation on.
        existing_user = self.db.execute(
            select(User).where(User.organization_id == config.organization_id, User.email == normalized_email)
        ).scalar_one_or_none()
        if existing_user is not None:
            self._link_identity(config, existing_user, subject)
            return existing_user, False

        if not config.jit_provisioning_enabled:
            raise IdentityError(
                ErrorCode.FEDERATION_USER_NOT_PROVISIONED,
                "No platform account exists for this identity, and just-in-time provisioning is disabled.",
            )

        user = self._provision_user(config, email=normalized_email, name=name, groups=groups)
        self._link_identity(config, user, subject)
        return user, True

    def _link_identity(self, config: FederationConfig, user: User, subject: str) -> None:
        self.db.add(FederatedIdentity(
            user_id=user.id, organization_id=config.organization_id, federation_config_id=config.id,
            external_subject_id=subject, last_federated_login_at=_now(),
        ))
        self.db.commit()

    def _provision_user(self, config: FederationConfig, *, email: str, name: str | None, groups: list[str]) -> User:
        role_names = claim_mapping.resolve_role_names(groups, config.claim_mappings)
        primary_role_id: uuid.UUID | None = None
        extra_roles: list[Role] = []
        if role_names:
            roles_by_name = {
                r.name: r for r in self.db.execute(
                    select(Role).where(Role.organization_id == config.organization_id, Role.name.in_(role_names))
                ).scalars()
            }
            resolved = [roles_by_name[n] for n in role_names if n in roles_by_name]
            if resolved:
                primary_role_id = resolved[0].id
                extra_roles = resolved[1:]
        if primary_role_id is None:
            primary_role_id = config.default_role_id  # may still be None -> VIEWER default

        first_name, last_name = _split_name(name, fallback_email=email)
        provisioning = UserProvisioningService(self.db)
        user = provisioning.provision(
            ProvisionRequest(
                organization_id=config.organization_id, email=email, first_name=first_name, last_name=last_name,
                password=None, role_id=primary_role_id,
            ),
            status=IdentityStatus.ACTIVE,
        )
        role_engine = RoleEngine(self.db)
        for role in extra_roles:
            role_engine.assign(user.id, role.id)
        self.db.commit()
        self.db.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    # Session issuance — the EXISTING pipeline, not a parallel one
    # (ACT-INT-FR-182). Mirrors AuthenticationService.login's own steps 7-8.
    # ------------------------------------------------------------------ #
    def _issue_session(
        self, user: User, *, login_method: str, is_new_user: bool,
        ip_address: str | None, user_agent: str | None, request_id: str | None,
    ) -> FederatedLoginResult:
        sessions = SessionLifecycleService(self.db)
        refresh_tokens = RefreshRotationService(self.db)
        resolver = IdentityContextResolver(self.db)
        tokens = TokenService(self.db)

        evicted = sessions.enforce_session_limit(user.id)
        for old in evicted:
            refresh_tokens.revoke_family(old.refresh_token_family_id)

        session = sessions.create(
            user.id, organization_id=user.organization_id, ip_address=ip_address, user_agent=user_agent,
            login_method=login_method,
        )
        issued = refresh_tokens.issue(session.id, session.refresh_token_family_id)

        auth_method = AuthMethod.OIDC if login_method == AuthMethod.OIDC.value else AuthMethod.SAML
        context = resolver.from_user(
            user, auth_method=auth_method, session_id=str(session.id),
            # AAL1, deliberately -- see module docstring.
            assurance_level=AuthAssuranceLevel.AAL1.value, amr=[login_method.lower()],
            ip_address=ip_address, user_agent=user_agent, request_id=request_id,
        )
        access = tokens.create_access_token(context)
        self.db.commit()
        return FederatedLoginResult(
            access_token=access, refresh_token=issued.token, session_id=session.id,
            context=context, is_new_user=is_new_user,
        )

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _active_config(self, organization_id: uuid.UUID, config_id: uuid.UUID, *, protocol: str) -> FederationConfig:
        config = self.get_config(organization_id, config_id)
        if config.protocol != protocol or not config.is_active:
            raise IdentityError(ErrorCode.FEDERATION_CONFIG_NOT_FOUND, "Federation configuration does not exist.")
        return config

    @staticmethod
    def _sign_flow_token(payload: Mapping[str, Any]) -> str:
        now = _now()
        claims = {
            **payload, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=_FLOW_TOKEN_TTL_SECONDS)).timestamp()),
        }
        return jose_jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def _verify_flow_token(token: str, *, purpose: str) -> dict[str, Any]:
        try:
            claims = jose_jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        except JOSEError as exc:
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "Login state is invalid or has expired.") from exc
        if claims.get("purpose") != purpose:
            raise IdentityError(ErrorCode.FEDERATION_STATE_INVALID, "Login state does not match this flow.")
        return claims


def _split_name(name: str | None, *, fallback_email: str) -> tuple[str, str]:
    if name and name.strip():
        parts = name.strip().split(maxsplit=1)
        return (parts[0], parts[1] if len(parts) > 1 else "")
    local_part = fallback_email.split("@", 1)[0]
    return (local_part, "")


def _first_attribute(attributes: Mapping[str, list[str]], name: str) -> str | None:
    values = attributes.get(name)
    return values[0] if values else None


def _validate_protocol_configuration(protocol: str, configuration: Mapping[str, Any]) -> None:
    if protocol == "OIDC":
        required = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri", "client_id")
    elif protocol == "SAML":
        required = ("idp_entity_id", "idp_sso_url", "idp_x509_cert", "sp_entity_id", "acs_url")
    else:
        raise IdentityError(ErrorCode.FEDERATION_CONFIG_INVALID, f"Unknown federation protocol '{protocol}'.")
    missing = [key for key in required if not configuration.get(key)]
    if missing:
        raise IdentityError(
            ErrorCode.FEDERATION_CONFIG_INVALID, f"Missing required configuration field(s): {', '.join(missing)}.",
        )
