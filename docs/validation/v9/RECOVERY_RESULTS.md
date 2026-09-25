# RECOVERY_RESULTS — M4.11 / M4.11a key continuity and M5 durable state under a real dump/restore

Raw: [`evidence/v9_recovery.json`](evidence/v9_recovery.json) (final run, restoring the **worst-case 100k**
database) and [`evidence/v9_recovery_on_worst10k.json`](evidence/v9_recovery_on_worst10k.json) (the earlier
run on the worst/10k database — identical key-continuity outcomes). Harness:
[`lab/scale/recovery.py`](../../../lab/scale/recovery.py) → [`recovery_step.py`](../../../lab/scale/recovery_step.py),
one interpreter per scenario, lab keys under `lab/.keys/v9rec/*` (gitignored), lab databases only, real
`pg_dump -Fc` / `pg_restore` from the PostgreSQL 17 binaries. **No secret appears in any artifact**: the
three plaintext test secrets travel in an environment variable between lab processes and are compared,
never echoed.

## The install under test

A fresh migrated database, bootstrapped through the product's own path (`bootstrap_key_material`): a new
Fernet key (`adopted_existing_key=false`), the `key_material_canary` row, the `installation_bootstrap`
marker, signing key `default` v1. Seeded through product paths: a provider credential and a tool credential
(ciphertext via `encrypt_secret`), a discovery source with an encrypted secret, and a NATIVE agent driven
through register → validate → identity → approve → activate → version → validate → approve → **publish**
(which calls `build_and_sign`; one `agent_version_signatures` row, `AttestationService.verify(...).valid = true`
before backup). Then `create_key_material_archive` (manifest + checksums verified intact) and `pg_dump`.

## §6.1 M4.11 key continuity

| scenario | expected | observed | pass |
|---|---|---|---|
| **R1 — restore WITH the key** (fresh DB ← dump; keys ← `restore_key_material_archive`) | existing ciphertext decrypts, historical signature verifies, new signing continues, install classifies EXISTING | `verify_key_material` → `key_state=OK`, `validation=CANARY_MATCH`, signing `OK` (1 key checked, signed state present), `install_mode=EXISTING_INSTALL`, marker present; provider credential / tool credential / discovery-source secret **all decrypt to the original plaintext**; historical signature **valid**, snapshot intact; a new version published after restore (validate/approve/publish all 200) and its signature **valid** | ✔ |
| **R2 — restore WITHOUT the key** (same dump, empty key directory) | fail loud; never silently regenerate | `verify_key_material` → `KeyMaterialError ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL`; with `allow_bootstrap=True` → same error; `bootstrap_key_material` → `BOOTSTRAP_REFUSED_MARKER_PRESENT`; `decrypt_secret` → `ENCRYPTION_KEY_MISSING`; **key directory still empty afterwards**, marker and canary rows byte-identical → `silent_identity_reset = false` | ✔ |
| **R3 — zero-ciphertext established install** (marker only: no canary, no ciphertext, no signed state) | classifies EXISTING; key cannot be silently adopted | `detect_install_mode` → `EXISTING_INSTALL` (marker=true, encrypted tables=[], signed tables=[]); with a key present, `verify_encryption_material` → `ENCRYPTION_KEY_UNVERIFIED_ESTABLISHED_INSTALL` (also with `allow_bootstrap=True`); with the key absent → `ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL`, no file created, marker unchanged | ✔ |
| **R4 — wrong key** (a different valid Fernet key) | fail loud | `ENCRYPTION_KEY_CANNOT_DECRYPT`; marker/canary unchanged | ✔ |
| **R4 — malformed key** (`not-a-fernet-key`) | fail loud | `ENCRYPTION_KEY_MALFORMED` | ✔ |
| **R4 — provider unavailable** (key path is a directory) | fail loud | `ENCRYPTION_KEY_PROVIDER_UNAVAILABLE` | ✔ |
| **R4 — unknown provider** (`ENCRYPTION_KEY_PROVIDER=VAULT`) | fail loud | `ENCRYPTION_KEY_PROVIDER_UNKNOWN` | ✔ |

**P0 check — silent cryptographic identity reset: none.** In every failing scenario the key directory was
unchanged afterwards (no file written), the bootstrap marker and canary rows were byte-identical, and the
error carried a distinct code with remediation text and no secret.

## §6.2–6.3 M5 durable state and transient state — restore of the worst-case 100k database

Disk guard (added after the host drive reached 97 %): free 9.68 GB, database 1.11 GB, need 2.99 GB → **fits,
nothing excluded**; the dump was deleted immediately after restore to reclaim space.

| item | value |
|---|---|
| `pg_dump -Fc` of the loaded database | **11.8 s**, 139.6 MB |
| `pg_restore -j 2` into a fresh database | **18.8 s** |
| consistency snapshot (count + md5 over every row, ordered) | 16.8 s before / 17.0 s after |
| tables compared | **31**, **all byte-identical** (count and md5) |

Durable rows that came back identical: `agents` **176,300** (100k fixture + reconciliation/sweep creations),
`control_graph_edges` **1,093,009**, `discovery_sources`, `discovery_runs`, `discovery_findings` 31,400,
`posture_findings` 19,651, `threat_findings`, `policies`, `runtime_governance_policies`,
`external_capability_grants` 200, `external_gateway_calls` 300,082, `assurance_evidence_bundles`,
`assurance_evaluations`, `budgets` 101 (limit sum preserved — **budgets not reset**), `budget_reservations`,
`runtime_alerts` 100 (**open alerts preserved**), `resources`, `tools`, `agent_executions` 121,550,
`agent_versions`, `delegations`, `agent_ownership_history`, `signing_keys`, `agent_version_signatures`,
`key_material_canary`, `installation_bootstrap`, `organizations`, `users`.

Consistency beyond counts: the RESOURCE-hub blast radius answers **40,148 agents before and 40,148 after**
the restore.

Transient state: `discovery_observations` **120,500** restored as-is — append-only evidence, re-derivable by
the next sweep, and nothing in the platform prunes it (`platform.expired_state_cleanup` reaps execution locks
and idempotency keys only — recorded, not judged). **No phantom live workers**: three `RUNNING` worker
registrations seeded before the dump were, after restore, detected stale by `WorkerFleetService.stale_workers`
(heartbeat older than `WORKER_STALE_AFTER_SECONDS=90`), reaped (`reap_stale_workers → 3`), and
`list_workers()` reports **no live worker**; the two expired `execution_locks` were gone after
`reap_expired_locks` (2 → 0).

## Recovery at scale (§6.4)

A restore of the 100k-agent / 1.09 M-edge inventory **completes in under 20 s and is consistent** (31/31 tables
identical, graph answer identical). Recovery is not only a small-database property.

## Verdict for §6

All properties pass: **M4.11 continuity intact** (decrypt / verify / sign after restore), **fail-loud holds** in
every degraded configuration, **zero-ciphertext established install classifies EXISTING** (M4.11a), **M5 durable
state survives restore byte-for-byte**, **no phantom workers**, **budgets and open alerts preserved**, **100k
restore consistent**. No P0.
