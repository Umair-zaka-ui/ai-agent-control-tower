"""Shared pytest fixtures + hermetic defaults.

Tests must not depend on the developer's ``.env`` or reach the network. The most
dangerous coupling is email: once real SMTP credentials are configured (so the app
can actually send onboarding mail), ``NOTIFICATIONS_ENABLED`` becomes true, and any
test that provisions an account would try to talk to a live SMTP server — flaky,
slow, and subject to the provider's rate limits.

So notifications are forced **off** for every test by default. A test that needs to
assert delivery behaviour opts back in explicitly with its own ``monkeypatch`` (see
``test_email_delivery.py``), which runs after this fixture and therefore wins.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _hermetic_notifications(monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Rate limiting is per-IP, but every test shares one client IP ("testclient"),
    so a live limiter would conflate unrelated tests and, once login became rate
    limited (4.2.2.3.4 §10), throttle the very attempts a lockout/flow test needs.

    So it is off by default. The dedicated rate-limit tests opt back in with their own
    ``RATE_LIMIT_ENABLED = True`` (which runs after this fixture and therefore wins)."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
