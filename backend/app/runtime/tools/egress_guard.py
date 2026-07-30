"""Phase 5.6a.1 SRS ACT-TLX-FR-004..010 — the SSRF containment boundary.

**Pure logic. No network I/O, no database, no dependency on any other
runtime module.** This is deliberate: the whole point of isolating this
component is that its correctness can be verified exhaustively, in
milliseconds, against every known bypass technique, without spinning up
anything — see ``backend/tests/runtime/test_egress_guard.py``. Any future
egress path (a second tool action type, a webhook callback, anything that
makes an outbound request influenced by model output) should call this
module rather than reimplementing address validation.

**The one question this module answers**: given a target URL and a
per-tool policy (an allowlist, a plaintext-http exception, and a set of
declared local-development hosts), is this request permitted — and if
not, which rule denied it. Nothing here decides *how* to connect (that is
``http_executor.py``'s job, which pins the actual TCP connection to the
IP this module validated — see its module docstring for why "resolve
then trust" is not enough).

Every rule below fails closed: a URL this module cannot confidently parse
or resolve is denied, never passed through on the assumption it's
probably fine.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# --------------------------------------------------------------------------- #
# Denial reason vocabulary — ACT-TLX-FR-011's ``egress_denied_reason`` column
# and the ``TOOL_EGRESS_DENIED`` error both use these exact strings, so a
# denial is always attributable to one specific rule, never a generic
# "no" (REPO_STATE §10.15 — never silently guess/collapse a reason).
# --------------------------------------------------------------------------- #
MALFORMED_URL = "MALFORMED_URL"
SCHEME_NOT_ALLOWED = "SCHEME_NOT_ALLOWED"
HOST_NOT_ALLOWLISTED = "HOST_NOT_ALLOWLISTED"
PRIVATE_ADDRESS = "PRIVATE_ADDRESS"
RESOLUTION_FAILED = "RESOLUTION_FAILED"
REDIRECT_DEPTH_EXCEEDED = "REDIRECT_DEPTH_EXCEEDED"

DEFAULT_MAX_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """The per-tool policy this module enforces against — built entirely
    from the *frozen* ``tools_snapshot`` document at call time
    (``ACT-TLX-FR-004``/``AC-16``), never from live, mutable ``Tool`` rows.
    Every field here is exactly what a tool definition declares; nothing
    here is supplied by model output."""

    allowed_hosts: frozenset[str]
    allow_plaintext_http: bool = False
    local_dev_hosts: frozenset[str] = field(default_factory=frozenset)
    max_redirects: int = DEFAULT_MAX_REDIRECTS

    def __post_init__(self) -> None:
        # Host comparisons throughout this module are lowercase; normalize
        # here once so every caller gets case-insensitive matching for
        # free, regardless of how a tool definition capitalized a host.
        object.__setattr__(self, "allowed_hosts", frozenset(h.lower() for h in self.allowed_hosts))
        object.__setattr__(self, "local_dev_hosts", frozenset(h.lower() for h in self.local_dev_hosts))


@dataclass(frozen=True, slots=True)
class EgressDecision:
    """The verdict for one URL. ``resolved_ip`` is set only when
    ``allowed`` is ``True`` — it is what ``http_executor.py`` pins the
    actual connection to (``ACT-TLX-FR-006``)."""

    allowed: bool
    reason: str | None
    host: str | None
    port: int | None
    scheme: str | None
    resolved_ip: str | None = None


# --------------------------------------------------------------------------- #
# Permissive IP-literal parsing — decimal/octal/hex encodings
#
# ``ipaddress.ip_address()`` only accepts standard dotted-quad/colon-hex
# forms; it raises on "2130706433" or "0177.0.0.1". Some platforms' libc
# resolvers (glibc's inet_aton family, which many Linux HTTP stacks use
# transitively) *do* accept these as IP literals during hostname
# resolution — which is exactly the bypass in ACT-TLX-FR-004's AC-04/AC-05.
# Relying on the OS resolver to reject them would make this guard's
# behavior platform-dependent (verified this session: it did **not**
# reject them via getaddrinfo on this Windows dev machine either, it just
# failed outright — a real Linux deployment's glibc resolver is documented
# to accept inet_aton-style literals, so this module never delegates that
# decision to the platform resolver at all). This parser is checked first,
# unconditionally, regardless of platform.
# --------------------------------------------------------------------------- #
def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Returns the address ``host`` denotes if it is *any* common IP
    literal form (standard, decimal, octal, hex, or the inet_aton
    partial-component forms), else ``None`` (meaning: not an IP literal at
    all, treat as a real hostname needing DNS resolution)."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    # Bracketed IPv6, e.g. from a URL's netloc.
    if host.startswith("[") and host.endswith("]"):
        try:
            return ipaddress.ip_address(host[1:-1])
        except ValueError:
            return None

    # Pure-integer decimal form: the whole host is one 32-bit number.
    if host.isdigit():
        try:
            value = int(host)
        except ValueError:
            return None
        if 0 <= value <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(value)
        return None

    # inet_aton-style dotted forms: 1-4 components, each decimal/octal/hex,
    # combined the same way C's inet_aton (and therefore many resolvers)
    # combine them -- the last component absorbs whatever bits remain.
    parts = host.split(".")
    if not (1 <= len(parts) <= 4):
        return None
    try:
        values = [_parse_component(part) for part in parts]
    except ValueError:
        return None
    if any(v is None for v in values):
        return None

    widths = {1: [32], 2: [8, 24], 3: [8, 8, 16], 4: [8, 8, 8, 8]}[len(values)]
    for v, width in zip(values, widths):
        if v >= (1 << width):
            return None
    total = 0
    for v, width in zip(values, widths):
        total = (total << width) | v
    return ipaddress.IPv4Address(total)


def _parse_component(part: str) -> int | None:
    """One dot-separated component of an inet_aton-style literal: ``0x``
    prefix is hex, a leading ``0`` (with more digits following) is octal,
    otherwise decimal -- the same precedence C's ``strtoul`` (and so
    ``inet_aton``) uses."""
    if part == "":
        return None
    try:
        if part.lower().startswith("0x"):
            return int(part, 16)
        if len(part) > 1 and part[0] == "0":
            return int(part, 8)
        return int(part, 10)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Address classification
# --------------------------------------------------------------------------- #
def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Everything that is not a routable public address: private, loopback
    (v4 and v6 — ``AC-02``), link-local (covers the cloud metadata address
    ``169.254.169.254``, ``AC-01``), unspecified (``0.0.0.0``, ``AC-03``),
    multicast, and reserved. An IPv4-mapped IPv6 address (``AC-06``, e.g.
    ``::ffff:127.0.0.1``) is unwrapped and the embedded IPv4 address is
    classified instead -- ``is_private``/``is_loopback`` on the *mapped*
    IPv6 form itself already return the right answer for the common case
    in this Python version, but unwrapping first makes that explicit
    rather than relying on it, and correctly handles a mapped address
    whose embedded IPv4 is blocked for a reason (e.g. link-local) that
    isn't otherwise obvious from the IPv6 address alone."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
Resolver = "callable[[str], list[str]]"  # host -> list of IP address strings


def _default_resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def resolve_and_validate(host: str, *, local_dev_hosts: frozenset[str], allow_plaintext_http: bool,
                         resolver=None) -> tuple[str | None, str | None]:
    """Returns ``(resolved_ip, denial_reason)`` — exactly one is ``None``.

    An IP literal in the host itself (any form ``_parse_ip_literal``
    recognizes) is validated directly, no DNS involved. Otherwise the
    ``resolver`` (real DNS by default; injectable so tests can simulate
    rebinding with no network at all) is consulted, and *every* returned
    address must be public — one bad address in the set is enough to deny
    (``AC-07``). Resolution failure denies rather than silently retrying
    or falling through (fail closed).

    The declared-local-dev exception (``ACT-TLX-FR-008``) only ever
    applies to a host *explicitly* named in ``local_dev_hosts`` — not to
    "any host that happens to resolve privately." Without this, the
    plaintext-http exception would be unusable (a local-dev target is, by
    definition, going to resolve to a loopback/private address), but it
    stays narrow: opting a specific declared host in does not open the
    private-address space generally."""
    literal = _parse_ip_literal(host)
    if literal is not None:
        candidates = [str(literal)]
    else:
        candidates = (resolver or _default_resolve)(host)
        if not candidates:
            return None, RESOLUTION_FAILED

    is_declared_local_dev = allow_plaintext_http and host in local_dev_hosts
    for candidate in candidates:
        ip = ipaddress.ip_address(candidate)
        if _is_blocked_address(ip) and not is_declared_local_dev:
            return None, PRIVATE_ADDRESS
    return candidates[0], None


# --------------------------------------------------------------------------- #
# The main entry point
# --------------------------------------------------------------------------- #
def evaluate_url(url: str, policy: EgressPolicy, *, resolver=None) -> EgressDecision:
    """Rules, in order, each failing closed (``ACT-TLX-FR-009`` — this
    always runs to completion *before* anything is connected to; it never
    inspects an already-issued request):

    1. Parse the URL.
    2. Scheme must be ``https``, or ``http`` only if the policy permits
       plaintext *and* the host is one of the policy's declared local-dev
       hosts (``ACT-TLX-FR-008``).
    3. Host must be on the policy's allowlist, exactly — never a value
       supplied by model output (``ACT-TLX-FR-010``; the caller is
       responsible for never constructing ``url`` from unvalidated model
       output in the first place — this function only ever sees the
       already-fixed target a tool definition declares).
    4. Resolve and validate every candidate address (``resolve_and_
       validate`` above)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return EgressDecision(False, MALFORMED_URL, None, None, None)

    host = parts.hostname
    if not parts.scheme or not host:
        return EgressDecision(False, MALFORMED_URL, host, parts.port, parts.scheme or None)

    scheme = parts.scheme.lower()
    host = host.lower()
    port = parts.port

    if scheme not in ("https", "http"):
        return EgressDecision(False, MALFORMED_URL, host, port, scheme)
    if scheme == "http" and not (policy.allow_plaintext_http and host in policy.local_dev_hosts):
        return EgressDecision(False, SCHEME_NOT_ALLOWED, host, port, scheme)

    if host not in policy.allowed_hosts:
        return EgressDecision(False, HOST_NOT_ALLOWLISTED, host, port, scheme)

    resolved_ip, denial = resolve_and_validate(
        host, local_dev_hosts=policy.local_dev_hosts, allow_plaintext_http=policy.allow_plaintext_http,
        resolver=resolver,
    )
    if denial is not None:
        return EgressDecision(False, denial, host, port, scheme)

    return EgressDecision(True, None, host, port, scheme, resolved_ip=resolved_ip)
