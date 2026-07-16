# Authorization Audit Center

Phase 4.3.7 §16. Complete, searchable event history across the authorization
platform.

## Event sources

- **Authorization events** — the six 4.3.6 pipeline events
  (`AUTHORIZATION_STARTED` … `EXECUTION_COMPLETED`) in the platform audit log,
  plus per-decision rows in `authorization_decisions`.
- **Administrative changes** — role/permission/assignment/hierarchy events
  (4.3.1), resource ownership/ACL/share/delegation events (4.3.4), ABAC policy
  lifecycle events (4.3.5) in the authorization audit trail.
- **Portal actions** — `SIMULATION_EXECUTED`, `DECISION_VIEWED`,
  `AUDIT_EXPORTED`, `ACCESS_REVIEW_*` (4.3.7 §22).

## Surfaces

- **Audit & Compliance Center** (`/audit`, Phase 3.5): search, filters,
  timeline, forensic detail with request/response viewers, correlation-id
  tracing and multi-format export.
- **Authorization audit** (Settings → Security → Authorization → Audit):
  the RBAC/ABAC change trail.
- **Decision explorer** (`/admin/decisions`): per-decision investigation —
  see [decision-explorer](decision-explorer.md).

Every export is itself audited; correlation ids link an audit row to the
pipeline trace of the decision that produced it.
