"""Phase 2.3.1 SRS ACT-INT-FR-180 — SAML 2.0 federated authentication:
web-browser SSO, XML-signature-verified assertions.

**Do not hand-roll XML signature verification or parsing.** SAML has a
well-documented history of signature-bypass classes (XML canonicalization
tricks, signature-wrapping attacks that smuggle attacker-controlled content
next to a validly-signed element and hope a naive parser reads the wrong
one). This module is a thin wrapper around **``python3-saml`` (OneLogin's
SP toolkit, version pinned in ``requirements.txt``), which delegates the
actual cryptographic and DOM work to ``xmlsec`` — a binding over
``libxmlsec1``, a security-focused C library purpose-built for this exact
problem.** No XML is parsed or signature-checked by hand anywhere in this
module.

**What defeats signature-wrapping here, specifically.** ``python3-saml``
resolves the element to trust by following the signature's own
``<Reference URI="#...">`` back to the *exact* element it covers (by ID),
the same discipline ``xmlsec`` implements at the C-library level — it does
not simply scan the document for "a signature" and separately extract "the
first assertion it finds." A wrapping attempt (an attacker-modified,
unsigned assertion placed near a validly-signed one) is defeated because
the library only ever trusts the element the signature's reference
actually names, verified directly in this phase's own test suite
(``test_saml_bypass_prevention.py``) using a hand-crafted wrapped
document.

**``strict: True`` is not optional.** It is always set on every settings
dict this module builds — it enables the toolkit's own schema validation
and additional security checks (destination/audience/timing conditions,
signature requirements) that non-strict mode relaxes for debugging only.
This module never constructs a settings dict with ``strict`` unset or
``False``.

**Replay/CSRF defense without a server-side "pending requests" table.**
This backend is stateless between the SSO redirect and the ACS callback —
there is no session yet (that is what this flow is establishing). Instead
of persisting the outgoing ``AuthnRequest``'s id, the id is embedded in a
platform-signed ``RelayState`` token (built by ``service.py``, verified by
signature + expiry before ever reaching this module) and handed back to
``verify_response`` as ``expected_request_id`` — the SAML response's own
``InResponseTo`` is required to match it exactly, which is what closes
both replay (an old, previously-consumed response cannot be presented
again for a *new* login attempt's expected id) and cross-flow substitution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlencode

_DEFAULT_NAME_ID_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"


class SamlVerificationError(Exception):
    """A SAML response failed verification — unsigned, wrongly signed,
    tampered, expired, wrong audience, or an InResponseTo mismatch. The
    message is always a generic, safe summary — never raw XML, a claim
    value, or the library's own internal error detail."""


@dataclass(frozen=True, slots=True)
class SamlClaims:
    """The verified, trustworthy identity carried by a SAML assertion —
    never constructed except by ``verify_response`` succeeding."""

    subject: str
    attributes: Mapping[str, list[str]] = field(default_factory=dict)


def build_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    """Translates this platform's own stored, non-secret configuration
    into the settings shape ``python3-saml`` expects. ``strict`` is always
    ``True`` — see module docstring."""
    return {
        "strict": True,
        "sp": {
            "entityId": config["sp_entity_id"],
            "assertionConsumerService": {
                "url": config["acs_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": config.get("name_id_format", _DEFAULT_NAME_ID_FORMAT),
        },
        "idp": {
            "entityId": config["idp_entity_id"],
            "singleSignOnService": {
                "url": config["idp_sso_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config["idp_x509_cert"],
        },
        "security": {
            # The assertion must be signed -- the whole point of this
            # module. The top-level message signature is not additionally
            # required (many IdPs sign only the assertion), but nothing
            # here is trusted unless the assertion's own signature verifies.
            "wantAssertionsSigned": True,
            "wantNameIdEncrypted": False,
            "requestedAuthnContext": False,
        },
    }


def build_request_data(
    *, https: bool, http_host: str, script_name: str,
    get_data: Mapping[str, str] | None = None, post_data: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The ``python3-saml`` "request data" shape, built from whatever a
    caller's own web framework request object exposes — this module has
    no FastAPI dependency itself, so ``service.py``/``routes.py`` do that
    translation."""
    return {
        "https": "on" if https else "off",
        "http_host": http_host,
        "script_name": script_name,
        "get_data": dict(get_data or {}),
        "post_data": dict(post_data or {}),
    }


def build_authn_request(settings_dict: Mapping[str, Any]) -> tuple[str, str]:
    """Builds a fresh AuthnRequest and returns ``(request_id,
    saml_request_base64)`` — the id is read *before* the caller builds any
    CSRF/replay-binding token, so it can be embedded in one (see module
    docstring)."""
    from onelogin.saml2.authn_request import OneLogin_Saml2_Authn_Request
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    settings = OneLogin_Saml2_Settings(dict(settings_dict))
    authn_request = OneLogin_Saml2_Authn_Request(settings)
    return authn_request.get_id(), authn_request.get_request()


def build_redirect_url(sso_url: str, saml_request: str, relay_state: str) -> str:
    return f"{sso_url}?{urlencode({'SAMLRequest': saml_request, 'RelayState': relay_state})}"


def sp_metadata_xml(settings_dict: Mapping[str, Any]) -> str:
    """The SP's own metadata document, for an IdP that wants to import it
    rather than being configured manually."""
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    settings = OneLogin_Saml2_Settings(dict(settings_dict), sp_validation_only=True)
    return settings.get_sp_metadata()


def verify_response(
    settings_dict: Mapping[str, Any], request_data: Mapping[str, Any], *, expected_request_id: str,
) -> SamlClaims:
    """The security core (see module docstring). Delegates every
    cryptographic/structural check to ``python3-saml``/``xmlsec`` — this
    function only orchestrates the call and translates the outcome.
    Raises ``SamlVerificationError`` for any failure; never returns a
    partially-verified result."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    auth = OneLogin_Saml2_Auth(dict(request_data), dict(settings_dict))
    try:
        auth.process_response(request_id=expected_request_id)
    except Exception as exc:  # noqa: BLE001 -- any library-level failure is a verification failure
        raise SamlVerificationError("SAML response could not be processed") from exc

    if auth.get_errors() or not auth.is_authenticated():
        raise SamlVerificationError("SAML assertion verification failed")

    subject = auth.get_nameid()
    if not subject:
        raise SamlVerificationError("SAML assertion carried no NameID")

    return SamlClaims(subject=subject, attributes=dict(auth.get_attributes() or {}))
