"""Pure unit tests: lifecycle transitions + password policy (no DB)."""

from __future__ import annotations

import pytest

from app.identity.models.enums import IdentityStatus, can_transition
from app.identity.security.passwords import PasswordPolicyError, validate_password


def test_valid_lifecycle_transitions() -> None:
    assert can_transition(IdentityStatus.CREATED, IdentityStatus.ACTIVE)
    assert can_transition(IdentityStatus.ACTIVE, IdentityStatus.SUSPENDED)
    assert can_transition(IdentityStatus.SUSPENDED, IdentityStatus.ACTIVE)
    assert can_transition(IdentityStatus.ARCHIVED, IdentityStatus.DELETED)


def test_invalid_lifecycle_transitions() -> None:
    # Cannot jump straight from CREATED to DELETED.
    assert not can_transition(IdentityStatus.CREATED, IdentityStatus.DELETED)
    # DELETED is terminal.
    assert not can_transition(IdentityStatus.DELETED, IdentityStatus.ACTIVE)
    # No-op transition is not allowed.
    assert not can_transition(IdentityStatus.ACTIVE, IdentityStatus.ACTIVE)


def test_password_policy() -> None:
    validate_password("Str0ngPass!x2")  # ok: mixed case + digit + length
    with pytest.raises(PasswordPolicyError):
        validate_password("short1A")  # too short
    with pytest.raises(PasswordPolicyError):
        validate_password("alllowercase1")  # no uppercase
    with pytest.raises(PasswordPolicyError):
        validate_password("NoDigitsHere")  # no digit
