"""Unit tests for the password policy engine (SRS §7, §8, §28).

These pin the *rules*, not the HTTP surface: complexity, sequence/repeat/common
detection, the strength calculator, temporary-password generation and history
pruning. The endpoints are exercised in ``test_credential_endpoints.py``.
"""

from __future__ import annotations

import string

import pytest

from app.identity.credentials import PasswordPolicyService, generate_temporary_password
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


# --------------------------------------------------------------------------- #
# Temporary-password generation.
#
# This block replaces a 50-draw version of the compliance test that flaked at
# roughly 2% per run. The flake was not a test problem: the generator returned
# its candidate unchecked, so ~1 draw in 2,200 genuinely violated the policy
# (measured: 9 in 20,000), and a 50-draw sample hit one about one run in fifty.
# The generator now validates and re-draws, so the correct assertion is the
# absolute one -- zero violations, at a sample size large enough that the old
# bug would be overwhelmingly likely to appear if it ever came back.
# --------------------------------------------------------------------------- #
_COMPLIANCE_DRAWS = 5_000


def test_generated_temporary_password_satisfies_policy() -> None:
    """AC-01/AC-06 -- deterministic in outcome, not flaky.

    A correct generator yields zero violations for any N, so this asserts
    exactly that. At 5,000 draws the pre-fix generator would have produced
    roughly two violations on average and would fail here better than 89% of
    runs, rising to certainty across CI runs."""
    violations: list[tuple[str, str]] = []
    for _ in range(_COMPLIANCE_DRAWS):
        password = generate_temporary_password()
        try:
            pol.validate_password(password)
        except pol.PasswordPolicyError as exc:
            violations.append((password, str(exc)))
    assert violations == [], f"{len(violations)} of {_COMPLIANCE_DRAWS} draws violated policy"


def test_generated_temporary_password_never_contains_a_sequence_or_repeat() -> None:
    """AC-03 -- the two content rules the old generator could actually trip,
    asserted directly against the policy's own detectors rather than inferred
    from ``validate_password`` not raising."""
    for _ in range(_COMPLIANCE_DRAWS):
        lowered = generate_temporary_password().lower()
        assert not pol._has_run(lowered), f"sequence in {lowered!r}"
        assert not pol._has_repeat(lowered), f"repeat in {lowered!r}"


def test_generated_temporary_password_respects_identity_context() -> None:
    """AC-03 -- the identity rule is context-dependent, so it can only be
    honoured when the caller supplies the user. ``PasswordResetService`` does;
    this pins that the generator acts on it rather than ignoring it."""
    for _ in range(200):
        password = generate_temporary_password(name="Ada Lovelace",
                                               email="ada@example.com")
        pol.validate_password(password, name="Ada Lovelace", email="ada@example.com")


def test_generator_calls_the_shared_policy_validator(monkeypatch) -> None:
    """AC-02, part 1 -- verified by call. The generator must run its candidate
    through the same entry point ``CredentialService._apply_new_password``
    uses, not a private copy of the rules."""
    seen: list[str] = []
    original = PasswordPolicyService.validate

    def _spy(password: str, *, user=None, **identity):
        seen.append(password)
        return original(password, user=user, **identity)

    monkeypatch.setattr(PasswordPolicyService, "validate", staticmethod(_spy))
    result = generate_temporary_password()
    assert seen, "the generator did not consult PasswordPolicyService.validate"
    assert seen[-1] == result, "the returned password was not the validated one"


def test_a_policy_change_automatically_applies_to_generation(monkeypatch) -> None:
    """AC-02, part 2 -- the point of reusing the validator rather than
    duplicating rules: a rule the generator has never heard of still binds it.

    A brand-new rule is injected into the shared policy module, and the
    generator is expected to honour it with no change of its own."""
    original = pol.validate_password

    def _stricter(password: str, **kwargs):
        original(password, **kwargs)
        if "7" in password:
            raise pol.PasswordPolicyError("no sevens allowed", code="PASSWORD_TOO_WEAK")

    monkeypatch.setattr(pol, "validate_password", _stricter)
    for _ in range(300):
        assert "7" not in generate_temporary_password()


def test_generator_raises_rather_than_returning_a_non_compliant_password(monkeypatch) -> None:
    """AC-04 -- the safety stop. If compliance is impossible the generator must
    fail loudly; handing back a password the login path will reject is the one
    outcome that is never acceptable."""
    def _reject_everything(password: str, *, user=None, **identity):
        raise pol.PasswordPolicyError("nothing is acceptable", code="PASSWORD_TOO_WEAK")

    monkeypatch.setattr(PasswordPolicyService, "validate", staticmethod(_reject_everything))
    with pytest.raises(RuntimeError, match="policy-compliant temporary password"):
        generate_temporary_password()


def test_generated_temporary_password_preserves_its_strength_properties() -> None:
    """AC-05 -- re-drawing must not have weakened the construction: length,
    all four character classes, a confined alphabet, and no collisions across
    a large sample (a crude but effective entropy sanity check)."""
    specials = "!@#$%^&*-_=+?"
    allowed = set(string.ascii_letters + string.digits + specials)
    seen: set[str] = set()

    for _ in range(1_000):
        password = generate_temporary_password()
        assert len(password) == 16
        assert any(c.isupper() for c in password)
        assert any(c.islower() for c in password)
        assert any(c.isdigit() for c in password)
        assert any(c in specials for c in password)
        assert set(password) <= allowed, f"unexpected characters in {password!r}"
        seen.add(password)

    assert len(seen) == 1_000, "generated passwords collided -- entropy is not what it should be"
