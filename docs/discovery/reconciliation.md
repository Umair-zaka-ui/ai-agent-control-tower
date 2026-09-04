# Reconciliation: deriving canonical state from evidence

`ReconciliationService` (`app/discovery/reconciliation.py`) is the only code
in this codebase that turns a `discovery_observations` row into a change to
the canonical `agents` registry — and it always does so through the Phase
5.1 server-authoritative seam (`AgentProvenanceService.record_external_agent`
for a new agent; a direct, discovery-metadata-only update for an existing
one). No adapter, and no other module, writes `agents` on discovery's
behalf.

## Matching: deterministic, explainable, no opaque ML

The sole identity signal is an **exact match** on
`(organization_id, external_reference)` — the column Phase 5.1 already gave
every agent, enforced unique by `uq_agents_org_external_ref`. There is no
fuzzy/name-similarity matching in this phase. A future phase could add one,
but it would need its own explicit, documented, testable scoring function —
never a black-box score a reader can't reconstruct from the inputs.

## The three outcomes

Every observation resolves to exactly one of:

| Outcome | When | Effect |
|---|---|---|
| **CREATE** | No agent claims this `external_reference` yet, and `confidence >= 0.75` | A new agent at `origin_category=EXTERNAL`, `control_state=DISCOVERED`, via `AgentProvenanceService.record_external_agent` |
| **LINK** | An existing `EXTERNAL`/`UNKNOWN` agent already claims it, and `confidence >= 0.75` | `last_observed_at`/`discovery_confidence`/`discovery_source_ref` updated. **Ownership, `control_state` and `lifecycle_status` are never touched.** |
| **FLAG** | `confidence < 0.75`, **or** the identifier already belongs to a `NATIVE` agent | A `discovery_findings` row (`RECONCILIATION_AMBIGUOUS`), `status=OPEN`. No automatic link, no automatic split, no agent created or modified. |

`LINK_CREATE_CONFIDENCE_THRESHOLD = 0.75` is a module constant, not a
per-call parameter — the same value applies everywhere, so the same evidence
always produces the same decision (`test_ac05_low_confidence_observation_is_flagged_not_auto_linked`).

**The NATIVE-conflict case is deliberate and tested**
(`test_ac05_conflict_with_a_native_agent_is_flagged_never_linked`): if a
discovered identifier happens to equal a NATIVE, ACT-governed agent's own
`external_reference`, that is a genuine conflict — an external system
claiming to be an agent ACT itself created and executes — and it is never
silently linked or ignored, only flagged, checked *before* the confidence
threshold so a high-confidence collision still gets caught.

## No silent merge, no silent split

The confidence gate and the NATIVE-conflict check are the entirety of the
"no silent merge" guarantee — there is no code path that links or creates
without going through them. A merge that *is* performed (a LINK) is
reversible in the sense that it only ever touches discovery metadata: the
agent's ownership, lifecycle and control state are exactly as they were, so
undoing a bad link is "correct the metadata" rather than "unwind an
irreversible mutation."

## Concurrency: one agent, never a duplicate

Two runs (or two threads of one run) racing to reconcile the same
`external_identifier` for the first time both see "no existing agent" under
READ COMMITTED — both attempt `record_external_agent`. The database's own
`uq_agents_org_external_ref` unique index decides the race: the loser's
`INSERT` raises `IntegrityError` at `flush()`, which `_reconcile_one` catches,
rolls back, re-reads, and **falls back to LINK against the winner's row** —
never a duplicate agent, never a raised error the caller has to handle
(`test_ac10_concurrent_reconciliation_of_the_same_external_agent_yields_one`,
proven with two real, separate Postgres sessions).

## Staleness: a finding, not a deletion

`ReconciliationService.check_staleness` runs after every sweep. For each
`EXTERNAL`/`UNKNOWN` agent linked to the source
(`Agent.discovery_source_ref == str(source.id)`):

- **Re-observed this run** → any `OPEN` `STALE_AGENT` finding for it is
  auto-`RESOLVED` (`test_ac08_reappearing_agent_resolves_the_staleness_finding`).
- **Missing this run** → the number of *prior* completed sweeps since
  `last_observed_at` is counted; once it reaches
  `DiscoverySource.missed_sweeps_before_stale` (default `1` — the very next
  miss raises), an `OPEN` `STALE_AGENT` finding is created. **The agent is
  never deleted and its `control_state` is never changed** — unknown does
  not mean unsafe, and missing evidence does not mean healthy; it means a
  named, reviewable, non-destructive finding
  (`test_ac08_disappeared_agent_yields_staleness_finding_not_deletion`).
- A partial unique index (`uq_discovery_findings_open_stale_agent`, one
  `OPEN` `STALE_AGENT` finding per agent) makes re-raising idempotent and
  safe under concurrent sweeps of the same source.

## Fails open, never gates

`ReconciliationService` is called only after a sweep's fetch has already
returned (successfully, degraded, or not at all — a hard fetch failure never
reaches it). Nothing here sits on an execution or governance path; a
reconciliation exception for one observation is caught per-item so one bad
observation degrades a run's counters, never crashes the sweep or the
platform.
