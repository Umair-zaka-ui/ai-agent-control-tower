"""Phase 4.1 -- the secret-scrubbing primitive (ACT-SRS-M4 §14).

**This module has no dependencies on this platform.** Not the models, not the
config, not the ORM, not even ``app.core``. Only the standard library. That is
deliberate, and it is the same discipline
``app/integration/connectors/storage/scope.py`` was built with: the one
function that decides whether a secret can reach persistent storage must be
readable, reviewable and exhaustively testable without standing a telemetry
pipeline up around it.

**What this is for.** Milestone 4 captures telemetry about executions. The
conservative baseline (:mod:`app.observability.capture`) means content is not
captured at all today, so in principle nothing here has anything to redact yet.
That is exactly why it exists now rather than later: the scrubber must already
be in the path before there is anything to scrub, so that no phase between here
and 4.8 can quietly widen capture and persist an unscrubbed secret. Scrubbing
is a property of the *write path*, never of the display layer (§14) -- a value
that reached the database unscrubbed is already leaked, and masking it in a UI
afterwards changes nothing.

**What "scrub" means here.** The value is *replaced*, not shortened, hinted at,
or hashed. ``mask_hint`` in ``app/runtime/providers/credential_crypto.py`` keeps
a four-character tail so a human can recognize a key they configured; that is a
different job with a different threat model (the operator is looking at their
own credential on purpose). Telemetry has no such need, so it keeps nothing.

**The two ways a secret is found.** By *key* -- the name says what the value is
("authorization", "api_key", "password") -- and by *shape* -- the value looks
like a credential regardless of what it is called (a ``Bearer`` header, an
``sk-`` key, a PEM block, an ``xoxb-`` token). Key matching alone is not enough,
because a secret carried under an innocuous name would survive it; shape
matching alone is not enough, because a high-entropy string is not reliably
distinguishable from a legitimate identifier. Both run, and either one is
sufficient to redact.
"""

from __future__ import annotations

import re
from typing import Any

# The literal that replaces any redacted value. Deliberately not empty and not
# ``None``: a reader must be able to tell "there was a secret here and it was
# removed" apart from "there was nothing here", or an audit of the telemetry
# plane cannot distinguish a working scrubber from an absent one.
REDACTED = "***REDACTED***"

# The maximum depth this walks before it stops descending. A pathologically
# nested structure must not be able to turn a best-effort telemetry write into
# a stack overflow that takes the execution down with it (§9 -- telemetry never
# gates execution).
MAX_DEPTH = 12

# --------------------------------------------------------------------------- #
# Secret classes (§14)
# --------------------------------------------------------------------------- #
# The named classes the SRS requires, each mapped to the key substrings that
# identify it. Keeping them as an explicit, named table rather than one flat
# regex is what lets the tests assert *coverage of the specification* -- "every
# class named in §14 is scrubbed" -- instead of asserting that a particular
# regex happens to match a particular string.
SECRET_CLASSES: dict[str, tuple[str, ...]] = {
    "authorization_header": ("authorization", "proxy-authorization", "www-authenticate"),
    "bearer_token": ("bearer", "access_token", "id_token", "jwt", "assertion"),
    "api_key": ("api_key", "apikey", "api-key", "x-api-key", "subscription_key",
                "client_secret", "consumer_secret", "app_secret"),
    "password": ("password", "passwd", "pwd", "passphrase", "secret"),
    "connector_credential": ("connector_credential", "credential", "credentials",
                             "connection_string", "dsn", "sas_token", "shared_access_key"),
    "provider_credential": ("provider_credential", "openai_api_key", "anthropic_api_key",
                            "aws_secret_access_key", "aws_session_token", "azure_key"),
    "refresh_token": ("refresh_token", "renewal_token", "offline_token"),
    "cookie": ("cookie", "set-cookie", "session_cookie", "csrf_token", "xsrf_token"),
    "private_key": ("private_key", "signing_key", "secret_key", "encryption_key",
                    "client_key", "tls_key", "ssh_key"),
}

# A key matches its class if the *normalized* key contains one of the patterns.
# Normalization folds case and collapses ``-``/``_``/``.``/space, so
# "X-Api-Key", "x_api_key" and "api key" are one thing.
_NORMALIZE = re.compile(r"[-_.\s]+")

# Keys that contain a secret-class substring but are demonstrably *not* secrets.
# Without this, "password_changed_at" (a timestamp), "has_password" (a boolean)
# and "credential_id" (a foreign key) would all be redacted, and the telemetry
# plane would lose ordinary operational facts to an over-eager matcher. Each of
# these is a value it is both safe and useful to keep.
_KEY_ALLOWLIST: frozenset[str] = frozenset({
    "passwordchangedat", "passwordupdatedat", "passwordexpiresat", "passwordage",
    "haspassword", "passwordrequired", "passwordpolicy", "passwordstrength",
    "credentialid", "credentialtype", "credentialscheme", "credentialref",
    "credentialcount", "apikeyid", "apikeyname", "apikeyprefix", "apikeylast4",
    "tokentype", "tokencount", "tokenusage", "prompttokens", "completiontokens",
    "totaltokens", "tokenaccountingcomplete", "secretreferences", "secretref",
    "cookieconsent", "privatekeyid", "signingkeyid", "signingkeyversion",
    "accesstokenttl", "refreshtokenttl", "accesstokenexpiresin",
})

# --------------------------------------------------------------------------- #
# Value-shape patterns -- a credential recognized by what it looks like
# --------------------------------------------------------------------------- #
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A whole authorization header value, however it is spelled.
    ("authorization_header", re.compile(r"^\s*(bearer|basic|digest|negotiate|hmac)\s+\S+",
                                        re.IGNORECASE)),
    # A JWT: three base64url segments separated by dots. Matches an id_token,
    # an access token and a bearer assertion alike.
    ("bearer_token", re.compile(r"^ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+$")),
    # Vendor-prefixed API keys. These prefixes are published by their vendors
    # precisely so that scanners can recognize a leaked key.
    ("api_key", re.compile(r"\b(sk|pk|rk|ak)-[A-Za-z0-9_-]{16,}")),
    ("api_key", re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}")),
    ("api_key", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("api_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    # Any PEM block -- RSA/EC/OPENSSH private keys, and the generic form.
    ("private_key", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----")),
    # A URL carrying inline credentials, e.g. postgres://user:pass@host/db.
    ("connector_credential", re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@",
                                        re.IGNORECASE)),
)


def normalize_key(key: str) -> str:
    """Fold a key to its comparable form: lowercase, no separators."""
    return _NORMALIZE.sub("", str(key)).lower()


def classify_key(key: str) -> str | None:
    """Return the §14 secret class this key names, or ``None``.

    Allowlisted keys (``password_changed_at`` and friends) return ``None`` even
    though they contain a class substring -- see ``_KEY_ALLOWLIST``."""
    normalized = normalize_key(key)
    if normalized in _KEY_ALLOWLIST:
        return None
    for class_name, patterns in SECRET_CLASSES.items():
        for pattern in patterns:
            if normalize_key(pattern) in normalized:
                return class_name
    return None


def classify_value(value: str) -> str | None:
    """Return the §14 secret class this *value* looks like, or ``None``.

    Shape matching, so a credential carried under an innocuous key -- the case
    key matching cannot catch -- is still caught."""
    if not isinstance(value, str) or not value.strip():
        return None
    for class_name, pattern in _VALUE_PATTERNS:
        if pattern.search(value):
            return class_name
    return None


def scrub_string(value: str) -> str:
    """Redact a bare string if its *shape* is a credential.

    A string with no credential shape is returned unchanged and identical --
    scrubbing must be transparent to ordinary values, or the telemetry plane
    becomes useless."""
    return REDACTED if classify_value(value) else value


def scrub(value: Any, *, _depth: int = 0) -> Any:
    """Return a scrubbed **copy** of ``value`` with every secret class removed.

    The input is never mutated: a caller must be able to scrub a payload for
    telemetry without altering the domain object it came from.

    Dicts are walked by key *and* by value; lists, tuples and sets are walked
    element-wise; every other type is returned as-is (an int cannot carry a
    secret in any way this can detect, and coercing it to a string to check
    would be worse than useless).

    Beyond ``MAX_DEPTH`` the structure is replaced wholesale rather than
    descended into. Truncating to a redaction marker is the safe direction: the
    alternative -- returning the un-walked subtree -- would persist exactly the
    thing this exists to prevent."""
    if _depth >= MAX_DEPTH:
        return REDACTED

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and classify_key(key) is not None:
                # The key names a secret: the value goes, whatever it is. A
                # nested structure under "credentials" is redacted whole rather
                # than walked, because every leaf under it is suspect.
                out[key] = REDACTED
            else:
                out[key] = scrub(item, _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        scrubbed = [scrub(item, _depth=_depth + 1) for item in value]
        return tuple(scrubbed) if isinstance(value, tuple) else scrubbed

    if isinstance(value, set):
        return {scrub(item, _depth=_depth + 1) for item in value}

    if isinstance(value, str):
        return scrub_string(value)

    return value


def contains_secret(value: Any) -> bool:
    """True if :func:`scrub` would change ``value``.

    The honest implementation of this question is to scrub and compare; a
    second, parallel detector would be a second thing to keep correct."""
    return scrub(value) != value
