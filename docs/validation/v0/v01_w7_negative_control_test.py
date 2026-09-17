"""V0.1 W-7 negative control (scratch, NOT committed).

Proves the corrected idempotency test still tests per-agent scoping: with the
product's IdempotencyService.check monkeypatched to an ORG-scoped lookup that
ignores agent_id (i.e. per-agent scoping broken), the test MUST fail.
Run from backend/:  pytest <this file> -q -p no:cacheprovider
"""
import importlib.util
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.runtime import IdempotencyRecord
from app.runtime import services as rt_services
from app.runtime.services import AgentExecution, IdempotencyService, _now

BACKEND = pathlib.Path(__file__).resolve()
TEST_FILE = pathlib.Path(r"C:\Users\PHS\Desktop\ai-agent-control-tower\backend\tests\authorization\test_runtime.py")
spec = importlib.util.spec_from_file_location("test_runtime_under_test", TEST_FILE)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def _org_scoped_check(self, principal, agent_id, key, request_hash):
    """The broken version: same org + same key => replay, whichever agent."""
    record = self.db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == principal.organization_id,
        IdempotencyRecord.idempotency_key == key,
    )).scalars().first()
    if record is None:
        return None
    if record.expires_at < _now():
        self.db.delete(record)
        self.db.flush()
        return None
    return self.db.get(AgentExecution, record.execution_id)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RESPONSE_ENVELOPE_ENABLED", False)


def test_corrected_test_fails_when_scoping_is_broken(monkeypatch):
    monkeypatch.setattr(IdempotencyService, "check", _org_scoped_check)
    client = TestClient(app)
    with pytest.raises(AssertionError):
        tr.test_idempotency_is_scoped_per_agent_not_shared(client)


def test_corrected_test_passes_with_real_scoping():
    client = TestClient(app)
    tr.test_idempotency_is_scoped_per_agent_not_shared(client)
