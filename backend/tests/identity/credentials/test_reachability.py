"""Guard against dead credential events/codes (this codebase's recurring defect).

Every credential audit event (§18) must be emitted somewhere, and every §26 error
code must be raised somewhere. A member defined but never referenced is a feature
that silently does nothing — so we grep the sources and fail if one is orphaned.
"""

from __future__ import annotations

import pathlib
import re

from app.identity.auth.enums import AuthEventType
from app.identity.errors import ErrorCode

_APP = pathlib.Path(__file__).resolve().parents[3] / "app"
_SOURCES = "\n".join(
    p.read_text(encoding="utf-8")
    for p in _APP.rglob("*.py")
    if p.name not in ("enums.py", "errors.py")
)

_CREDENTIAL_EVENTS = [
    AuthEventType.PASSWORD_CREATED,
    AuthEventType.PASSWORD_CHANGED,
    AuthEventType.PASSWORD_RESET,
    AuthEventType.PASSWORD_EXPIRED,
    AuthEventType.PASSWORD_ROTATED,
    AuthEventType.PASSWORD_REUSED_ATTEMPT,
    AuthEventType.TEMP_PASSWORD_CREATED,
    AuthEventType.FIRST_LOGIN_PASSWORD_CHANGED,
    AuthEventType.PASSWORD_POLICY_VIOLATION,
]

_CREDENTIAL_CODES = [
    ErrorCode.PASSWORD_TOO_WEAK,
    ErrorCode.PASSWORD_REUSED,
    ErrorCode.INVALID_CURRENT_PASSWORD,
    ErrorCode.PASSWORD_POLICY_FAILED,
    ErrorCode.PASSWORD_MIN_AGE,
]


def test_every_credential_event_is_emitted() -> None:
    dead = [
        e.name for e in _CREDENTIAL_EVENTS if not re.search(rf"AuthEventType\.{e.name}\b", _SOURCES)
    ]
    assert not dead, f"credential audit events defined but never emitted: {dead}"


def test_every_credential_error_code_is_raised() -> None:
    # A code counts as reachable if raised via ``ErrorCode.X`` *or* as the string
    # literal ``"X"`` — the policy engine raises PASSWORD_TOO_WEAK / PASSWORD_POLICY_
    # FAILED through ``PasswordPolicyError(code=...)`` rather than the enum attribute.
    dead = [
        c for c in _CREDENTIAL_CODES
        if not re.search(rf'(ErrorCode\.{c}\b|"{c}")', _SOURCES)
    ]
    assert not dead, f"credential error codes defined but never raised: {dead}"
