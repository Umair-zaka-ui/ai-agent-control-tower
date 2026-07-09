# Testing strategy

_Phase 4.2.2.3.5 §17–§21. How the Enterprise Identity Platform is tested, and where the
coverage actually stands._

## The pyramid (§17)

| Layer | What it covers | Where |
|-------|----------------|-------|
| **Unit** | Pure logic: password policy & strength, risk scoring, lockout maths, token hashing, rule evaluation | `backend/tests/identity/**/test_*_unit.py`, `test_password_policy_unit.py`, `test_scoring_and_rules_unit.py` |
| **API / integration** | Every endpoint through a real `TestClient` against a real Postgres: success, validation, permission, expiry/revocation, rate limits, enumeration-safety | `backend/tests/identity/**` (auth, credentials, recovery, registration, protection, integration) |
| **Reachability** | Guards against the codebase's recurring "built but never called" defect — every error code / audit event / decision must be reached by a test | `test_reachability.py`, `test_rules_and_reachability.py`, `test_recovery_events_and_reachability.py` |
| **Frontend component** | Forms, validation, protected routes, session expiry, password-strength meter, security console | `frontend/src/**/*.test.tsx` (vitest + @testing-library) |

## Measured coverage

Backend line coverage is **measured, not assumed**:

```
python -m pytest --cov=app.identity --cov=app.core --cov-report=term-missing
```

- **346 tests passing**; **92%** line coverage on `app.identity` + `app.core`
  (§17 unit target: 90%).
- Frontend: **211 tests passing**; `tsc --noEmit` and the production build are clean.

Lower-coverage modules are thin repository/query helpers exercised indirectly through the
API tests; the security-critical surfaces (`security/passwords.py` 95%, protection
`detection`/`lockout`/`policy`, recovery and credential services) are covered directly.

## Hermetic defaults (why the suite is deterministic)

`backend/tests/conftest.py` forces two things off for every test so the suite never
depends on a developer's `.env` or the network, and never flakes on shared state:

- **Notifications off** — no test hits a live SMTP server. Delivery tests opt back in
  explicitly (they run after the autouse fixture and win).
- **Rate limiting off** — every `TestClient` shares one client IP, so a live per-IP
  limiter would conflate unrelated tests. The dedicated rate-limit tests re-enable it.

> **Operational note.** The tests use the same Postgres database as the local dev server.
> A `uvicorn` instance left running on `:8002` writes to that database _during_ a test
> run and causes spurious failures. Stop the dev server before a full-suite or coverage
> run, then restart it.

## End-to-end journeys (§21)

The §21 journeys — invite→register→verify→login, forgot→reset→login, admin
lock→denied→unlock→login, session-expiry→silent-refresh, multi-device→logout-all — are
each covered at the API/integration layer end-to-end. A browser-driver E2E harness
(Playwright) is deferred to a future phase; the flows themselves are exercised today
through the integration suite and manually in the SPA.
