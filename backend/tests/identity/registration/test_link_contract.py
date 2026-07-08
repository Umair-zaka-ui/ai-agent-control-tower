"""The emailed link must match the route the SPA actually serves.

If either side renames its path, every invitation and verification link in flight lands
on a 404 — and no test on either side alone would notice. The frontend half is pinned by
`frontend/src/modules/identity/tests/linkContract.test.ts`.
"""

from __future__ import annotations

from app.core.config import settings
from app.identity.email import invitation_url, verification_url


def test_invitation_link_shape() -> None:
    assert invitation_url("inv_abc") == f"{settings.APP_BASE_URL.rstrip('/')}/invite/inv_abc"


def test_verification_link_shape() -> None:
    assert verification_url("vrf_abc") == f"{settings.APP_BASE_URL.rstrip('/')}/verify-email/vrf_abc"


def test_tokens_are_url_encoded_so_a_stray_slash_cannot_break_the_route() -> None:
    assert "/" not in invitation_url("a/b").rsplit("/invite/", 1)[1]


def test_a_trailing_slash_on_the_base_url_does_not_double_up(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.example.com/")
    assert invitation_url("t") == "https://app.example.com/invite/t"
