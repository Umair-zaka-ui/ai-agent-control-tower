"""Phase 2.3.1 tests — SAML 2.0 assertion verification bypass prevention
(``app/identity/federation/saml.py::verify_response``), the security
core's second half.

Every test in this file verifies a real, genuinely ``xmlsec``-signed SAML
XML response (built by this directory's own ``_saml_fixtures.py`` test
helper — never a mock signer) against ``python3-saml``'s own toolkit —
with **no live IdP, no HTTP call, no database** anywhere in the file."""

from __future__ import annotations

import base64
import datetime
import uuid

import pytest
from lxml import etree

from app.identity.federation import saml
from tests.identity.federation import _saml_fixtures as fx

_SP_ENTITY_ID = "https://platform.example.com/sp"
_ACS_URL = "https://platform.example.com/api/v1/auth/federation/org1/saml/acs"
_IDP_ENTITY_ID = "https://idp.example.com"
_IDP_SSO_URL = "https://idp.example.com/sso"
_SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
_SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"


@pytest.fixture()
def idp_cert():
    return fx.generate_idp_certificate()


def _settings_dict(cert):
    return saml.build_settings({
        "idp_entity_id": _IDP_ENTITY_ID, "idp_sso_url": _IDP_SSO_URL, "idp_x509_cert": cert.cert_body_b64,
        "sp_entity_id": _SP_ENTITY_ID, "acs_url": _ACS_URL,
    })


def _request_data(b64_response: str, relay_state: str = "test-relay-state") -> dict:
    return saml.build_request_data(
        https=True, http_host="platform.example.com", script_name="/api/v1/auth/federation/org1/saml/acs",
        post_data={"SAMLResponse": b64_response, "RelayState": relay_state},
    )


def _fresh_ids() -> tuple[str, str, str]:
    return (f"_req{uuid.uuid4().hex[:10]}", f"_assertion{uuid.uuid4().hex[:10]}", f"_resp{uuid.uuid4().hex[:10]}")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _build_signed_response(
    cert, *, request_id: str, assertion_id: str, subject: str = "alice-subject-123",
    sp_entity_id: str = _SP_ENTITY_ID,
    not_before: datetime.datetime | None = None, not_after: datetime.datetime | None = None,
    attributes: dict[str, list[str]] | None = None, sign: bool = True,
) -> etree._Element:
    now = _now()
    assertion = fx.build_assertion_xml(
        assertion_id=assertion_id, idp_entity_id=_IDP_ENTITY_ID, sp_entity_id=sp_entity_id, acs_url=_ACS_URL,
        subject=subject, in_response_to=request_id,
        not_before=not_before or (now - datetime.timedelta(minutes=5)),
        not_after=not_after or (now + datetime.timedelta(minutes=5)),
        attributes=attributes or {"email": ["alice@example.com"], "name": ["Alice Example"], "groups": ["AI-Admins"]},
    )
    response = fx.build_response_xml(
        response_id=f"_r{uuid.uuid4().hex[:10]}", in_response_to=request_id, idp_entity_id=_IDP_ENTITY_ID,
        acs_url=_ACS_URL, assertion=assertion,
    )
    if sign:
        fx.sign_element(response, element_id=assertion_id, cert=cert)
    return response


# --------------------------------------------------------------------------- #
# AC-12 — a validly-signed assertion, correct conditions, authenticates
# --------------------------------------------------------------------------- #
def test_ac12_a_validly_signed_response_authenticates(idp_cert):
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id)
    b64 = fx.to_base64(response)

    claims = saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)
    assert claims.subject == "alice-subject-123"
    assert claims.attributes["email"] == ["alice@example.com"]
    assert claims.attributes["groups"] == ["AI-Admins"]


# --------------------------------------------------------------------------- #
# AC-13 — unsigned or wrongly-signed assertion rejected
# --------------------------------------------------------------------------- #
def test_ac13_an_unsigned_assertion_is_rejected(idp_cert):
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id, sign=False)
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


def test_ac13_a_tampered_after_signing_assertion_is_rejected(idp_cert):
    """The signature is genuine — for the *original* content. Content
    changed after signing must invalidate it, exactly as a JWT's
    signature invalidates on tampering."""
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id, subject="alice-subject-123")
    xml_bytes = etree.tostring(response)
    tampered = xml_bytes.replace(b">alice-subject-123<", b">attacker-admin-9999<")
    assert tampered != xml_bytes  # the replace actually did something
    b64 = base64.b64encode(tampered).decode("ascii")

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


def test_ac13_signed_by_an_untrusted_certificate_is_rejected(idp_cert):
    """A structurally well-formed, internally-consistent signature — but
    made with a *different* key than the one this SP's configuration
    trusts for this IdP. Must be rejected exactly like a JWT signed by
    the wrong key."""
    request_id, assertion_id, _ = _fresh_ids()
    untrusted_cert = fx.generate_idp_certificate()
    response = _build_signed_response(untrusted_cert, request_id=request_id, assertion_id=assertion_id)
    b64 = fx.to_base64(response)

    # verify against the ORIGINAL (trusted) cert's settings, not the one
    # that actually signed the response
    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


# --------------------------------------------------------------------------- #
# AC-14 — expired / wrong-audience assertion rejected
# --------------------------------------------------------------------------- #
def test_ac14_an_expired_assertion_is_rejected(idp_cert):
    request_id, assertion_id, _ = _fresh_ids()
    now = _now()
    response = _build_signed_response(
        idp_cert, request_id=request_id, assertion_id=assertion_id,
        not_before=now - datetime.timedelta(minutes=30), not_after=now - datetime.timedelta(minutes=20),
    )
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


def test_ac14_a_wrong_audience_assertion_is_rejected(idp_cert):
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(
        idp_cert, request_id=request_id, assertion_id=assertion_id, sp_entity_id="https://someone-else.example.com/sp",
    )
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


def test_ac14_a_response_not_matching_the_expected_request_id_is_rejected(idp_cert):
    """InResponseTo binding — the replay/CSRF defense (service.py's own
    signed RelayState is what supplies the *expected* id in production;
    here it is passed directly to isolate this one check)."""
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id)
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id="a-different-request-id")


# --------------------------------------------------------------------------- #
# AC-15 — signature-wrapping attempt rejected
# --------------------------------------------------------------------------- #
def test_ac15_a_signature_wrapping_attempt_is_rejected(idp_cert):
    """The classic SAML wrapping shape: a validly-signed, legitimate
    assertion sits in the document, and an attacker-controlled, UNSIGNED
    assertion (different subject/attributes) is injected alongside it,
    hoping a naive processor extracts claims from the wrong (unsigned)
    one while merely confirming "some signature is present and valid"
    for the other. ``python3-saml``/``xmlsec`` follow the signature's own
    ID-based reference to the exact element it covers — this is rejected
    outright, never silently trusting the forged assertion's claims."""
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id, subject="alice-legit")

    forged_id = f"_forged{uuid.uuid4().hex[:10]}"
    forged = fx.build_assertion_xml(
        assertion_id=forged_id, idp_entity_id=_IDP_ENTITY_ID, sp_entity_id=_SP_ENTITY_ID, acs_url=_ACS_URL,
        subject="attacker-admin", in_response_to=request_id,
        not_before=_now() - datetime.timedelta(minutes=5), not_after=_now() + datetime.timedelta(minutes=5),
        attributes={"email": ["attacker@evil.example.com"]},
    )
    # Inserted as the FIRST assertion child, ahead of the legitimately
    # signed one -- the shape a naive "take the first Assertion" reader
    # would be fooled by.
    response.insert(2, forged)
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError) as excinfo:
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)
    # Never leaks which element or why -- a generic, safe message, exactly
    # like every other verification failure in this module.
    assert "attacker" not in str(excinfo.value).lower()


def test_ac15_wrapping_via_an_extensions_element_is_also_rejected(idp_cert):
    """A second wrapping shape: the legitimately-signed assertion is
    moved into a ``<samlp:Extensions>`` wrapper (out of the normal
    processing path) and a forged, unsigned assertion takes its place as
    the response's only direct-child assertion."""
    request_id, assertion_id, _ = _fresh_ids()
    response = _build_signed_response(idp_cert, request_id=request_id, assertion_id=assertion_id, subject="alice-legit")

    signed_assertion_node = response.find(f"{{{_SAML_NS}}}Assertion")
    response.remove(signed_assertion_node)
    extensions = etree.SubElement(response, f"{{{_SAMLP_NS}}}Extensions")
    extensions.append(signed_assertion_node)

    forged_id = f"_forged{uuid.uuid4().hex[:10]}"
    forged = fx.build_assertion_xml(
        assertion_id=forged_id, idp_entity_id=_IDP_ENTITY_ID, sp_entity_id=_SP_ENTITY_ID, acs_url=_ACS_URL,
        subject="attacker-admin", in_response_to=request_id,
        not_before=_now() - datetime.timedelta(minutes=5), not_after=_now() + datetime.timedelta(minutes=5),
        attributes={"email": ["attacker@evil.example.com"]},
    )
    response.append(forged)
    b64 = fx.to_base64(response)

    with pytest.raises(saml.SamlVerificationError):
        saml.verify_response(_settings_dict(idp_cert), _request_data(b64), expected_request_id=request_id)


# --------------------------------------------------------------------------- #
# AC-16 — verification uses a vetted library, not hand-rolled
# --------------------------------------------------------------------------- #
def test_ac16_verification_delegates_to_python3_saml_and_xmlsec_not_hand_rolled():
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[3].joinpath(
        "app", "identity", "federation", "saml.py",
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    assert "onelogin" in imported
    # No direct XML parsing/crypto primitives -- everything XML-shaped is
    # handled by the onelogin toolkit (and, underneath it, xmlsec), never
    # assembled from raw `lxml`/`hashlib`/`cryptography` calls in this file.
    assert "lxml" not in imported
    assert "hashlib" not in imported
    assert "xmlsec" not in imported


def test_ac16_strict_mode_is_always_enabled():
    """`strict: True` enables python3-saml's own schema validation and
    additional security checks -- structurally proven, not just asserted
    by convention, so a future edit can't silently relax it."""
    settings_dict = saml.build_settings({
        "idp_entity_id": _IDP_ENTITY_ID, "idp_sso_url": _IDP_SSO_URL, "idp_x509_cert": "dummy",
        "sp_entity_id": _SP_ENTITY_ID, "acs_url": _ACS_URL,
    })
    assert settings_dict["strict"] is True


def test_ac16_wants_assertions_signed_is_always_required():
    settings_dict = saml.build_settings({
        "idp_entity_id": _IDP_ENTITY_ID, "idp_sso_url": _IDP_SSO_URL, "idp_x509_cert": "dummy",
        "sp_entity_id": _SP_ENTITY_ID, "acs_url": _ACS_URL,
    })
    assert settings_dict["security"]["wantAssertionsSigned"] is True
