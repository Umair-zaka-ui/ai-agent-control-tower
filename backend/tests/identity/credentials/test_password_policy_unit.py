"""Unit tests for the password policy engine (SRS §7, §8, §28).

These pin the *rules*, not the HTTP surface: complexity, sequence/repeat/common
detection, the strength calculator, temporary-password generation and history
pruning. The endpoints are exercised in ``test_credential_endpoints.py``.
"""

from __future__ import annotations

import pytest

from app.identity.credentials import generate_temporary_password
from app.identity.security import passwords as pol


@pytest.mark.parametrize(
    "password",
    [
        "short1!A",              # too short
        "alllowercase123!",      # no uppercase
        "ALLUPPERCASE123!",      # no lowercase
        "NoNumbersHere!!",       # no digit
        "NoSpecials12345",       # no special
        "password123!AA",        # decorated common password (prefix)
        "admin123!ABcd",         # decorated common password (prefix)
        "MyPass1234!wxyz",       # numeric sequence 1234
        "Zxcvbn9!qwerAB",        # keyboard sequence qwer
        "Aaaa1111!!!!bbbb",      # 4x repeat
    ],
)
def test_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(pol.PasswordPolicyError):
        pol.validate_password(password)


@pytest.mark.parametrize(
    "password",
    ["Zt9$mQ2!vLp7Xw", "MyStr0ng!Vault#42", "Wolf-Tree_88!Rains"],
)
def test_policy_accepts_strong_passwords(password: str) -> None:
    pol.validate_password(password)  # must not raise


def test_policy_rejects_identity_substrings() -> None:
    with pytest.raises(pol.PasswordPolicyError):
        pol.validate_password("Ada-Lovelace99!", name="Ada Lovelace")
    with pytest.raises(pol.PasswordPolicyError):
        pol.validate_password("Acme-Corp-99!Xy", organization_name="Acme Corp")
    with pytest.raises(pol.PasswordPolicyError):
        pol.validate_password("ada99!StrongXY", email="ada@example.com")


def test_weak_password_carries_machine_code() -> None:
    with pytest.raises(pol.PasswordPolicyError) as exc:
        pol.validate_password("short1!A")
    assert exc.value.code == "PASSWORD_TOO_WEAK"


def test_strength_levels_are_ordered() -> None:
    empty = pol.estimate_strength("")
    weak = pol.estimate_strength("abc")
    strong = pol.estimate_strength("Zt9$mQ2!vLp7Xw")
    stronger = pol.estimate_strength("Zt9$mQ2!vLp7Xw-Rainy-Owl")
    assert empty["level"] == "very_weak" and empty["meets_policy"] is False
    assert weak["meets_policy"] is False
    assert strong["meets_policy"] is True
    assert stronger["score"] >= strong["score"]
    assert stronger["level"] in ("strong", "very_strong")


def test_failing_password_can_never_be_advertised_acceptable() -> None:
    """A password that fails the gate must not be scored above 'weak' — the meter
    must never tell a user a rejected password is fine."""
    result = pol.estimate_strength("password123!AA")
    assert result["meets_policy"] is False
    assert result["level"] in ("very_weak", "weak")
    assert result["feedback"]


def test_generated_temporary_password_satisfies_policy() -> None:
    for _ in range(50):
        pol.validate_password(generate_temporary_password())
