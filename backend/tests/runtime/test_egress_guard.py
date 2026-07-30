"""Phase 5.6a.1 tests — the isolated SSRF egress guard.

No network, no database (AC-26): every DNS answer in this file is
injected via a fake resolver. Each SSRF vector from the build prompt gets
its own dedicated test (AC-01..10), not one combined test, so a
regression in any single rule shows up by name.
"""

from __future__ import annotations

import pytest

from app.runtime.tools.egress_guard import (
    HOST_NOT_ALLOWLISTED,
    MALFORMED_URL,
    PRIVATE_ADDRESS,
    RESOLUTION_FAILED,
    SCHEME_NOT_ALLOWED,
    EgressPolicy,
    evaluate_url,
    resolve_and_validate,
)


def _policy(*, hosts=("api.example.com",), plaintext=False, local_dev=()) -> EgressPolicy:
    return EgressPolicy(allowed_hosts=frozenset(hosts), allow_plaintext_http=plaintext,
                        local_dev_hosts=frozenset(local_dev))


def _resolver(mapping: dict[str, list[str]]):
    def _resolve(host: str) -> list[str]:
        return mapping.get(host, [])
    return _resolve


# --------------------------------------------------------------------------- #
# AC-01..06 — the six concrete SSRF address vectors
# --------------------------------------------------------------------------- #
def test_cloud_metadata_address_is_denied() -> None:
    """AC-01 — http://169.254.169.254/. No local-dev exception configured
    (that exception is opt-in, per-host, and declared by an administrator
    — never something a request itself can invoke) — denied on the
    address alone."""
    policy = _policy(hosts=("169.254.169.254",))
    decision = evaluate_url("https://169.254.169.254/latest/meta-data/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


@pytest.mark.parametrize("host,url", [
    ("localhost", "https://localhost/"),
    ("127.0.0.1", "https://127.0.0.1/"),
    ("[::1]", "https://[::1]/"),
])
def test_loopback_addresses_are_denied(host: str, url: str) -> None:
    """AC-02 — localhost, 127.0.0.1, [::1] (v4 and v6)."""
    bare_host = host.strip("[]")
    policy = _policy(hosts=(bare_host,))
    resolver = _resolver({bare_host: [bare_host if bare_host != "localhost" else "127.0.0.1"]})
    decision = evaluate_url(url, policy, resolver=resolver)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_unspecified_address_is_denied() -> None:
    """AC-03 — 0.0.0.0."""
    policy = _policy(hosts=("0.0.0.0",))
    decision = evaluate_url("https://0.0.0.0/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_decimal_encoded_loopback_is_denied() -> None:
    """AC-04 — http://2130706433/ (127.0.0.1 as a decimal integer)."""
    policy = _policy(hosts=("2130706433",))
    decision = evaluate_url("https://2130706433/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_octal_encoded_loopback_is_denied() -> None:
    """AC-05 — http://0177.0.0.1/ (octal 0177 == decimal 127)."""
    policy = _policy(hosts=("0177.0.0.1",))
    decision = evaluate_url("https://0177.0.0.1/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_ipv4_mapped_ipv6_loopback_is_denied() -> None:
    """AC-06 — http://[::ffff:127.0.0.1]/."""
    policy = _policy(hosts=("::ffff:127.0.0.1",))
    decision = evaluate_url("https://[::ffff:127.0.0.1]/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


# --------------------------------------------------------------------------- #
# AC-07 — an allowlisted hostname resolving to a private address
# --------------------------------------------------------------------------- #
def test_allowlisted_hostname_resolving_to_private_ip_is_denied() -> None:
    """AC-07 — being on the allowlist is not enough; the resolved address
    is independently validated every time."""
    policy = _policy(hosts=("internal-looking-name.example.com",))
    resolver = _resolver({"internal-looking-name.example.com": ["10.0.0.5"]})
    decision = evaluate_url("https://internal-looking-name.example.com/", policy, resolver=resolver)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_allowlisted_hostname_resolving_to_public_ip_is_allowed() -> None:
    """Positive control for AC-07 — proves the denial above is really
    about the address, not something else about the host."""
    policy = _policy(hosts=("api.example.com",))
    resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    decision = evaluate_url("https://api.example.com/v1/data", policy, resolver=resolver)
    assert decision.allowed is True
    assert decision.resolved_ip == "93.184.216.34"


# --------------------------------------------------------------------------- #
# AC-08 — DNS rebinding: public on the first resolve, private on the second
# --------------------------------------------------------------------------- #
def test_dns_rebinding_second_resolution_is_independently_denied() -> None:
    """AC-08 — the guard-level half of rebinding defense: every call to
    ``evaluate_url``/``resolve_and_validate`` independently validates
    whatever the resolver returns *at that moment*, with no cached trust
    from an earlier call. A resolver simulating rebinding (public first,
    private on every call after) is denied on the second evaluation.
    (The executor-level half — pinning the connection to the *first*
    validated IP so a second resolution never actually happens at connect
    time — is proven in ``test_http_tool_execution.py``.)"""
    calls = {"n": 0}

    def _rebinding_resolver(host: str) -> list[str]:
        calls["n"] += 1
        return ["93.184.216.34"] if calls["n"] == 1 else ["127.0.0.1"]

    policy = _policy(hosts=("api.example.com",))
    first = evaluate_url("https://api.example.com/", policy, resolver=_rebinding_resolver)
    assert first.allowed is True
    assert first.resolved_ip == "93.184.216.34"

    second = evaluate_url("https://api.example.com/", policy, resolver=_rebinding_resolver)
    assert second.allowed is False
    assert second.reason == PRIVATE_ADDRESS


# --------------------------------------------------------------------------- #
# AC-10 — a model-supplied URL cannot override the allowlist
# --------------------------------------------------------------------------- #
def test_url_outside_the_allowlist_is_denied_regardless_of_source() -> None:
    """AC-10 (guard-level) — the guard has no notion of "trusted" vs.
    "model-supplied" URLs; it denies anything off the allowlist
    unconditionally. (The architectural guarantee that a tool's actual
    request host is never *constructed* from model output in the first
    place is proven in ``test_http_tool_execution.py``.)"""
    policy = _policy(hosts=("api.example.com",))
    decision = evaluate_url("https://attacker.example.net/exfiltrate", policy)
    assert decision.allowed is False
    assert decision.reason == HOST_NOT_ALLOWLISTED


# --------------------------------------------------------------------------- #
# Fail-closed on malformed input and resolution failure
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", ["", "not a url", "https://", "ftp://api.example.com/", "://broken"])
def test_malformed_or_unsupported_scheme_url_is_denied(url: str) -> None:
    policy = _policy(hosts=("api.example.com",))
    decision = evaluate_url(url, policy)
    assert decision.allowed is False
    assert decision.reason in (MALFORMED_URL, SCHEME_NOT_ALLOWED, HOST_NOT_ALLOWLISTED)


def test_resolution_failure_denies_rather_than_falling_through() -> None:
    policy = _policy(hosts=("api.example.com",))
    resolver = _resolver({})  # empty -- simulates NXDOMAIN
    decision = evaluate_url("https://api.example.com/", policy, resolver=resolver)
    assert decision.allowed is False
    assert decision.reason == RESOLUTION_FAILED


def test_any_single_private_candidate_among_multiple_denies_the_whole_resolution() -> None:
    """A hostname resolving to *both* a public and a private address is
    denied outright -- one bad candidate is enough (conservative by
    design: an attacker doesn't get to pick which of several answers the
    connection actually uses)."""
    policy = _policy(hosts=("multi.example.com",))
    resolver = _resolver({"multi.example.com": ["93.184.216.34", "127.0.0.1"]})
    decision = evaluate_url("https://multi.example.com/", policy, resolver=resolver)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


# --------------------------------------------------------------------------- #
# HTTPS enforcement & the narrow local-dev exception
# --------------------------------------------------------------------------- #
def test_plaintext_http_denied_by_default() -> None:
    policy = _policy(hosts=("api.example.com",))
    decision = evaluate_url("http://api.example.com/", policy)
    assert decision.allowed is False
    assert decision.reason == SCHEME_NOT_ALLOWED


def test_plaintext_http_denied_even_when_allowed_generally_if_host_not_declared_local_dev() -> None:
    """Plaintext being permitted for the tool does not open plaintext to
    *every* allowlisted host -- only to hosts explicitly declared local-dev."""
    policy = _policy(hosts=("api.example.com",), plaintext=True, local_dev=("other-host.example.com",))
    decision = evaluate_url("http://api.example.com/", policy)
    assert decision.allowed is False
    assert decision.reason == SCHEME_NOT_ALLOWED


def test_plaintext_http_allowed_for_declared_local_dev_host() -> None:
    """The narrow, explicit exception: a host must be both on the
    allowlist *and* individually declared as a local-dev host before
    plaintext (and, necessarily, its private address) is permitted."""
    policy = _policy(hosts=("localhost",), plaintext=True, local_dev=("localhost",))
    resolver = _resolver({"localhost": ["127.0.0.1"]})
    decision = evaluate_url("http://localhost:11434/api/generate", policy, resolver=resolver)
    assert decision.allowed is True
    assert decision.resolved_ip == "127.0.0.1"


def test_declared_local_dev_host_still_denied_if_not_on_allowlist() -> None:
    """Declaring a host as local-dev does not implicitly allowlist it —
    both conditions are required independently."""
    policy = _policy(hosts=("api.example.com",), plaintext=True, local_dev=("localhost",))
    resolver = _resolver({"localhost": ["127.0.0.1"]})
    decision = evaluate_url("http://localhost/", policy, resolver=resolver)
    assert decision.allowed is False
    assert decision.reason == HOST_NOT_ALLOWLISTED


# --------------------------------------------------------------------------- #
# IP-literal parsing — direct unit coverage of the permissive parser itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("literal", [
    "2130706433", "0177.0.0.1", "0x7f000001", "0x7f.0.0.1", "127.1",
])
def test_permissive_ip_literal_parser_recognizes_alternate_loopback_encodings(literal: str) -> None:
    policy = _policy(hosts=(literal,))
    decision = evaluate_url(f"https://{literal}/", policy)
    assert decision.allowed is False
    assert decision.reason == PRIVATE_ADDRESS


def test_permissive_parser_does_not_misclassify_a_real_hostname_as_an_ip() -> None:
    """A dotted hostname made of digit-looking labels that isn't actually
    a valid inet_aton-style literal (a label out of range) is correctly
    treated as a real hostname needing DNS resolution, not silently
    coerced into an IP."""
    policy = _policy(hosts=("999.999.999.999.example.com",))
    resolver = _resolver({"999.999.999.999.example.com": ["93.184.216.34"]})
    decision = evaluate_url("https://999.999.999.999.example.com/", policy, resolver=resolver)
    assert decision.allowed is True


# --------------------------------------------------------------------------- #
# Host allowlist matching is case-insensitive and exact
# --------------------------------------------------------------------------- #
def test_host_matching_is_case_insensitive() -> None:
    policy = _policy(hosts=("API.Example.com",))
    resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    decision = evaluate_url("https://API.EXAMPLE.COM/", policy, resolver=resolver)
    assert decision.allowed is True


def test_subdomain_of_an_allowlisted_host_is_not_implicitly_allowed() -> None:
    """No implicit subdomain/suffix matching -- an allowlist entry means
    exactly that host, not "that host and anything under it," which would
    otherwise let a tool definition's intent be silently widened."""
    policy = _policy(hosts=("api.example.com",))
    decision = evaluate_url("https://evil.api.example.com/", policy)
    assert decision.allowed is False
    assert decision.reason == HOST_NOT_ALLOWLISTED


# --------------------------------------------------------------------------- #
# resolve_and_validate() exercised directly (not only via evaluate_url)
# --------------------------------------------------------------------------- #
def test_resolve_and_validate_direct() -> None:
    resolver = _resolver({"good.example.com": ["93.184.216.34"]})
    ip, reason = resolve_and_validate("good.example.com", local_dev_hosts=frozenset(), allow_plaintext_http=False,
                                      resolver=resolver)
    assert ip == "93.184.216.34"
    assert reason is None
