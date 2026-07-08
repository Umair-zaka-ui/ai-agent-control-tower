# ADR-0002 — PostgreSQL as the sole datastore

- **Status:** Accepted *(retroactively recorded 2026-07-08; decision made in Phase 1)*
- **Deciders:** Platform engineering
- **Supersedes:** —

## Context

The platform stores relational, strongly-referential data: organisations own
users, agents, policies and actions; approvals reference actions; audit rows
reference organisations. It also stores schemaless-ish blobs — `input_payload`,
`conditions`, `capabilities`, `before_state`/`after_state`, `meta` — which
are naturally JSON.

The obvious pull is toward polyglot persistence: Postgres for the relations, a
document store for the JSON, Redis for sessions and rate limits, maybe
Elasticsearch for audit search. That is the conventional "grown-up" answer, and
it is what most SaaS platforms of this size have.

Constraints in play:

- The audit trail is the product's primary asset. It must be transactionally
  consistent with the decision it describes — an `agent_actions` row and its
  `audit_logs` row must commit or fail together.
- Small team. Every additional datastore is an operational surface: backups,
  restores, upgrades, monitoring, a second consistency model, a second failure
  mode during an incident.
- Current scale is modest. There is no measured performance problem.

## Options considered

### Option A — Postgres + MongoDB for JSON payloads
- Pros: document-native storage for payloads and policy conditions.
- Cons: **no cross-store transaction.** An audit row in Mongo and an action row in
  Postgres can diverge — precisely the failure the audit trail exists to prevent.
  Two backup/restore stories. Two consistency models to reason about at 3am.

### Option B — Postgres + Redis (sessions, rate limits, token denylist)
- Pros: fast session lookup; a natural home for a future token denylist.
- Cons: sessions are already in Postgres and are not hot. Redis is durable-ish,
  not durable; a session/denylist store that loses data fails *open*. Adds a
  dependency to satisfy a problem we do not yet have.

### Option C — PostgreSQL only, using JSONB for semi-structured columns
- Pros: one datastore. ACID across the entire governance pipeline. JSONB is
  indexable (GIN) and queryable. One backup, one restore, one upgrade path.
- Cons: no document-store ergonomics. Postgres becomes the scaling bottleneck.
  Some workloads (full-text audit search, high-frequency counters) are a poorer
  fit than a purpose-built store.

## Decision

We chose **Option C: PostgreSQL 16 only.** JSONB carries every semi-structured
column. Sessions, refresh tokens, login history and security events are ordinary
tables.

Option A is rejected on correctness, not taste: `process_agent_action` writes the
action and its audit record in one transaction. Split those across stores and the
system's central guarantee — *every decision is recorded* — degrades to *every
decision is usually recorded*. That is not a governance platform.

Option B is rejected as premature. Sessions are read once per refresh, not per
request (see [ADR-0003](./0003-stateless-jwt-with-rotating-refresh-tokens.md)),
so there is no hot path to cache.

## Consequences

### Positive
- The governance pipeline is atomic end-to-end: permission → decision → action row
  → audit row commit together, or not at all.
- One thing to back up, restore, secure, patch and monitor.
- Local dev is `docker compose up -d db`. No fixture orchestration.
- JSONB + GIN covers policy-condition and payload queries at current scale.

### Negative / accepted cost
- **Postgres is the single scaling bottleneck and single point of failure.** Read
  replicas mitigate the first; nothing here mitigates the second.
- Audit search is `LIKE`/JSONB-operator based. It will not scale to full-text
  search over hundreds of millions of rows.
- No natural home for per-IP rate-limit counters, which is part of why rate
  limiting is still an open gap
  ([threat model P0](../security/threat-model.md#prioritised-remediation)).
- If the [access-token revocation gap](./0003-stateless-jwt-with-rotating-refresh-tokens.md)
  is ever closed with a denylist, that denylist must live in Postgres and will be
  read on **every** authenticated request. At current scale an indexed table is
  fine. At 10× it is the first thing that breaks.

### Residual risk
`act_pgdata` is currently the only copy of the audit trail. No backups, no PITR
([deployment gap 10](../deployment/deployment.md#gaps-before-production)). The
sole-datastore decision *concentrates* this risk — the argument for one store is
only sound if that store is genuinely durable, which today it is not.

## Revisit when

- Audit search latency exceeds ~1s at p95 → consider a read replica or a search index.
- A second API replica is needed **and** a token denylist is required → re-evaluate Redis.
- Sustained write throughput approaches the primary's capacity → partition
  `audit_logs` / `login_history` before adding a datastore.
