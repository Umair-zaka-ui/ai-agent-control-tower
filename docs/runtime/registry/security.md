# Security (§69)

Builds on Phase 5.0's default-deny/tenant-isolation posture (see
[../security.md](../security.md)) rather than introducing a second security
model.

## Tenant isolation

Every new resource follows the same `get_or_404`-through-organization_id
pattern Phase 5.0 established: ownership history, machine identity,
validation runs, duplicate matches, import/export jobs, and lifecycle
events all 404 (not 403) on a cross-tenant lookup — confirmed by
`test_cross_tenant_agent_lookup_denied`,
`test_cross_tenant_ownership_history_denied`,
`test_cross_tenant_duplicate_matches_denied` in
`backend/tests/authorization/test_agent_registry.py`.

## Optimistic concurrency (§53)

`Agent.row_version` uses SQLAlchemy's native `version_id_col` — every
`UPDATE` includes `WHERE row_version = <the value this session loaded>`,
and a concurrent write in between raises `StaleDataError`. On top of that,
`AgentRegistryService.update` does an explicit **client-visible** check:
the caller must submit the `row_version` they last read, and a mismatch
raises `AGENT_CONCURRENT_MODIFICATION` (409) *before* anything is written —
this is the part SQLAlchemy's own mechanism doesn't give you for free (it
protects concurrent *sessions*, not a client's claimed version), so both
checks run: the manual one for the common case, the native one as
defense-in-depth against a genuine race between the check and the commit.

## Direct status-column bypass is structurally impossible

`AgentRegistryUpdate` (the PATCH schema) has no `lifecycle_status` field at
all — Pydantic silently drops unknown fields by default, so a client
sending `{"lifecycle_status": "ACTIVE", ...}` has that key ignored before it
ever reaches the service layer. Verified by
`test_update_cannot_bypass_lifecycle_status_directly`.

## Credential handling

- `documentation_url`/`repository_url` reject embedded credentials
  (`scheme://user:pass@host`) at both registration and update time.
- Export always excludes secret-shaped definition fields via an allowlist,
  not a denylist (see [import-export.md](import-export.md)).
- YAML import uses `yaml.safe_load` exclusively.
- CSV export neutralizes formula injection.

## Duplicate identity assignment

`agent_identities.agent_id` is now uniquely constrained — an identity can
never silently attach to two agents, closing a gap Phase 5.0 left entirely
unenforced (no constraint existed, and `status`/`expires_at` were never
read anywhere before this phase).

## Performance (§31)

`backend/tests/authorization/test_agent_registry_perf.py` follows the same
timing-reported-not-asserted convention as
`test_permission_engine_perf.py`/`test_resource_authorization_perf.py`:
bulk-registers 50 agents and exercises paginated/filtered search against
the resulting inventory, and runs duplicate detection against a 50+ agent
candidate pool — asserting correctness under load (every agent findable,
duplicates still detected) while reporting throughput.
