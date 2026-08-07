"""Test-only SAML response construction and signing helpers (Phase 2.3.1).

**This module exists only in the test suite.** Nothing in the shipped
``app/identity/federation/saml.py`` ever constructs or signs a SAML
assertion — the platform is a Service Provider (a verifier), never an
Identity Provider (an issuer); building signed assertions is exactly what
a *real* IdP does, and this file exists purely to give the bypass-
prevention tests real, genuinely signed (and deliberately tampered) XML
to verify against, using the same ``xmlsec`` library the shipped
verification path relies on."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field

import xmlsec
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

_SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
_SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
_NSMAP = {"samlp": _SAMLP, "saml": _SAML}


@dataclass(frozen=True, slots=True)
class IdpCertificate:
    private_key_pem: str
    cert_pem: str  # full PEM, headers included -- what xmlsec needs to sign/verify
    cert_body_b64: str  # header/footer-stripped -- what a SAML settings dict's x509cert expects


def generate_idp_certificate() -> IdpCertificate:
    """A real, freshly-generated self-signed cert — never shared across
    tests, so a verification bug can't hide behind key/cert reuse."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp.example.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode("ascii")
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    body = "".join(
        line for line in cert_pem.splitlines() if line and "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
    )
    return IdpCertificate(private_key_pem=private_pem, cert_pem=cert_pem, cert_body_b64=body)


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_assertion_xml(
    *, assertion_id: str, idp_entity_id: str, sp_entity_id: str, acs_url: str, subject: str, in_response_to: str,
    not_before: datetime.datetime, not_after: datetime.datetime, attributes: dict[str, list[str]] | None = None,
) -> etree._Element:
    now = datetime.datetime.now(datetime.timezone.utc)
    assertion = etree.Element(f"{{{_SAML}}}Assertion", nsmap=_NSMAP, attrib={
        "ID": assertion_id, "Version": "2.0", "IssueInstant": _iso(now),
    })
    issuer = etree.SubElement(assertion, f"{{{_SAML}}}Issuer")
    issuer.text = idp_entity_id

    subject_el = etree.SubElement(assertion, f"{{{_SAML}}}Subject")
    name_id = etree.SubElement(subject_el, f"{{{_SAML}}}NameID", attrib={
        "Format": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
    })
    name_id.text = subject
    confirmation = etree.SubElement(subject_el, f"{{{_SAML}}}SubjectConfirmation", attrib={
        "Method": "urn:oasis:names:tc:SAML:2.0:cm:bearer",
    })
    etree.SubElement(confirmation, f"{{{_SAML}}}SubjectConfirmationData", attrib={
        "NotOnOrAfter": _iso(not_after), "Recipient": acs_url, "InResponseTo": in_response_to,
    })

    conditions = etree.SubElement(assertion, f"{{{_SAML}}}Conditions", attrib={
        "NotBefore": _iso(not_before), "NotOnOrAfter": _iso(not_after),
    })
    audience_restriction = etree.SubElement(conditions, f"{{{_SAML}}}AudienceRestriction")
    audience = etree.SubElement(audience_restriction, f"{{{_SAML}}}Audience")
    audience.text = sp_entity_id

    authn = etree.SubElement(assertion, f"{{{_SAML}}}AuthnStatement", attrib={
        "AuthnInstant": _iso(now), "SessionIndex": f"_session-{uuid.uuid4().hex[:8]}",
    })
    authn_context = etree.SubElement(authn, f"{{{_SAML}}}AuthnContext")
    class_ref = etree.SubElement(authn_context, f"{{{_SAML}}}AuthnContextClassRef")
    class_ref.text = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"

    if attributes:
        attr_statement = etree.SubElement(assertion, f"{{{_SAML}}}AttributeStatement")
        for name, values in attributes.items():
            attr = etree.SubElement(attr_statement, f"{{{_SAML}}}Attribute", attrib={"Name": name})
            for value in values:
                value_el = etree.SubElement(attr, f"{{{_SAML}}}AttributeValue")
                value_el.text = value

    return assertion


def sign_element(root: etree._Element, *, element_id: str, cert: IdpCertificate, insert_at: int = 1) -> None:
    """Signs the element with the given ``ID`` attribute (an enveloped
    signature, inserted as the element's own child at ``insert_at`` —
    position 1, right after ``<Issuer>``, is where every SAML consumer,
    including ``python3-saml``, expects to find it)."""
    xmlsec.tree.add_ids(root, ["ID"])
    target = root if root.get("ID") == element_id else root.find(f".//*[@ID='{element_id}']")
    signature_node = xmlsec.template.create(
        target, xmlsec.constants.TransformExclC14N, xmlsec.constants.TransformRsaSha256,
    )
    ref = xmlsec.template.add_reference(signature_node, xmlsec.constants.TransformSha256, uri=f"#{element_id}")
    xmlsec.template.add_transform(ref, xmlsec.constants.TransformEnveloped)
    xmlsec.template.add_transform(ref, xmlsec.constants.TransformExclC14N)
    key_info = xmlsec.template.ensure_key_info(signature_node)
    xmlsec.template.add_x509_data(key_info)
    target.insert(insert_at, signature_node)

    ctx = xmlsec.SignatureContext()
    ctx.key = xmlsec.Key.from_memory(cert.private_key_pem, xmlsec.KeyFormat.PEM)
    ctx.key.load_cert_from_memory(cert.cert_pem, xmlsec.KeyFormat.PEM)
    ctx.sign(signature_node)


def build_response_xml(
    *, response_id: str, in_response_to: str, idp_entity_id: str, acs_url: str, assertion: etree._Element,
    extra_assertions: list[etree._Element] | None = None,
) -> etree._Element:
    now = datetime.datetime.now(datetime.timezone.utc)
    response = etree.Element(f"{{{_SAMLP}}}Response", nsmap=_NSMAP, attrib={
        "ID": response_id, "Version": "2.0", "IssueInstant": _iso(now),
        "Destination": acs_url, "InResponseTo": in_response_to,
    })
    issuer = etree.SubElement(response, f"{{{_SAML}}}Issuer")
    issuer.text = idp_entity_id
    status = etree.SubElement(response, f"{{{_SAMLP}}}Status")
    status_code = etree.SubElement(status, f"{{{_SAMLP}}}StatusCode")
    status_code.set("Value", "urn:oasis:names:tc:SAML:2.0:status:Success")
    for extra in (extra_assertions or []):
        response.append(extra)
    response.append(assertion)
    return response


def to_base64(root: etree._Element) -> str:
    import base64

    return base64.b64encode(etree.tostring(root)).decode("ascii")
