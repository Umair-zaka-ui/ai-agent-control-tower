# Backup and system-migration guide

**Last verified 2026-08-28** after Phase 4.5 (behavioral signals). Facts that matter for a restore,
all re-checked live rather than carried forward: migration head
**`0049_behavioral_signals`**, **129 tables** (128 in `Base.metadata` — Alembic
owns `alembic_version` and it is not a model), PostgreSQL **17.10** locally,
`backend/.venv` on Python **3.13.14**, Node **v24.18.0**. Sections naming a
version were corrected in the 2026-08-14 pass — the previous text said Python
3.12 and Node 22 LTS, and its `py -3.12 -m venv` command would now fail outright
on this machine.

Phase 3.7 introduced the first automation that moves production traffic without
a human, so this guide covers **in-flight rollback state**; Phase 3.8 added the
distributed scheduler that drives it, so it now also covers **scheduler state
and lease recovery**. Read both before restoring into anything that will serve
traffic.

**Phase 4.1 adds durable state, and it is deliberately trivial to recover.** The
telemetry plane is *derived* (see
[ADR-0008](docs/architecture/adr/0008-telemetry-as-a-derived-plane.md)), so
nothing in it is authoritative and nothing in it needs special handling:

- `runtime_events` rows are **best-effort observations**, not records of what
  happened. Losing some in a restore loses observability of a window, never the
  record of an execution — that lives in `agent_executions` and its children,
  which are durable and unchanged by this phase.
- **Traces need no recovery at all.** Spans are not stored; they are recomputed
  by pure function from the domain rows. A restored database produces
  byte-identical span ids for every execution it contains.
- The **capture baseline is durable configuration, and it is a constant**:
  `METADATA_ONLY`, defined in `app/observability/capture.py`, not in the
  database and not in an environment variable. A restore cannot lose it, and a
  misconfigured environment cannot silently widen it. Phase 4.8 moves this to
  per-environment policy, at which point it becomes restorable state and this
  section must be revisited.
- `agent_executions.request_id` and `runtime_events.span_id` are nullable and
  were never backfilled, so a restore to a pre-4.1 dump followed by
  `alembic upgrade head` produces a correct, fully-traceable database with those
  two columns simply empty for historical rows.

**Phase 4.2 adds no durable state at all — deliberately.** It measured whether
trace assembly needed a materialized read projection and concluded it does not
(0.74ms p50 at 90,695 executions; see
[ADR-0008](docs/architecture/adr/0008-telemetry-as-a-derived-plane.md)), so
there is no derived store to rebuild, re-sync or reconcile after a restore. Its
one migration adds an **index**, which Postgres rebuilds from the table itself:
nothing to back up separately, nothing that can be stale, and a restore that
replays migrations gets it automatically. The trace explorer is a pure read over
`agent_executions` and its children, so it is correct the instant those tables
are.

**Phase 4.3 adds durable state that is *governing*, and that changes the
restore calculus.** The two previous Milestone 4 phases added observability,
which can be lost without consequence. This one adds rules that stop
executions, and the governance plane **fails closed** — so what happens after a
restore depends on which half you get back.

- **`runtime_governance_policies` is durable configuration and must be
  restored.** Losing it does not corrupt anything, but it silently *removes
  governance*: executions resume running under the built-in loop-safety caps
  alone, with every cost ceiling, restricted-model rule and approval obligation
  gone. Nothing errors, nothing looks wrong, and the platform is less governed
  than the operator believes. Treat a restore that omits this table the same way
  you would treat one that omitted RBAC grants.
- **A partially restored policy set is worse than none**, and it is the one
  shape to check for deliberately. If the `mandatory` policies came back and the
  advisory ones did not, the platform is *stricter* than intended; if the
  reverse, it is looser. After a restore, compare the policy count and the
  `mandatory` flags against the dump manifest before serving traffic.
- **`runtime_governance_decisions` is append-only evidence, not operating
  state.** Nothing reads it to make a decision; it exists to answer *why did
  this execution stop*. Losing rows loses history, never behaviour. The database
  revokes `UPDATE`/`DELETE` from `PUBLIC`, so a restored dump preserves that
  property only if it is replayed through `alembic upgrade head` rather than
  loaded schema-and-all into a database whose grants were set up by hand.
- **A mid-execution governance decision does not survive a restart, and does not
  need to.** The engine holds no state between checkpoints beyond the policy
  snapshot it resolved when the loop began — that snapshot is rebuilt from
  `runtime_governance_policies` on the next attempt. An execution interrupted
  mid-loop is recovered by the *existing* worker machinery (lease expiry →
  `reap_expired_locks` → the retry policy, Phase 3.9), and the retried attempt
  is governed from scratch by whatever policies are in force then. There is no
  half-finished governance state to reconcile.
- **A governance stop is not retried, and that is the intended behaviour after a
  restore too.** `GOVERNANCE_EXECUTION_STOPPED` and `KILL_SWITCH_ACTIVE` are
  non-retryable, so an execution stopped by governance before the snapshot stays
  stopped afterwards. `GOVERNANCE_CHECKPOINT_UNEVALUABLE` *is* retryable — it
  means the platform could not evaluate a mandatory rule, which is exactly the
  condition a restore fixes.
- **The failure mode to plan for: a restored database whose policy store is
  unreachable.** Governance fails closed, so every execution governed by a
  mandatory policy will STOP with `GOVERNANCE_CHECKPOINT_UNEVALUABLE` until it
  is reachable again. That is correct and deliberate, and it is also a way for
  one table to halt the platform. If you are restoring into something that must
  serve traffic immediately, verify `runtime_governance_policies` is queryable
  *before* starting the workers.

**Phase 4.4 adds durable state that is *financial*, and a restore can get it
wrong in two opposite directions.** Phase 4.3 added rules that stop executions;
this adds an accounting ledger, and a ledger can be restored too full or too
empty. Both are bad, differently.

- **`budgets` is durable configuration and must be restored.** Losing it
  removes every ceiling: executions resume running with no limit, nothing
  errors, and the platform is less governed than the operator believes —
  exactly the failure mode described for `runtime_governance_policies` above,
  with money attached. Treat a restore that omits this table the way you would
  one that omitted RBAC grants.
- **`budget_reservations` is not observability — it is the accounting.** This
  is the important difference from every other Milestone 4 table. A restore
  that loses reservation rows does not merely lose history: it **gives budget
  back that was actually spent**, because a budget's committed total is the sum
  of its `RESERVED` and `RECONCILED` rows. A tenant restored to yesterday's
  reservations has yesterday's headroom and today's already-paid provider
  bill.
- **A restore can also leave holds that no longer correspond to anything.**
  Rows in `RESERVED` whose executions were never restored (or were restored in
  a terminal state) consume headroom for work that will never run. Run the
  orphan sweep after restoring — it releases exactly those, and only those:
  holds whose execution has reached a terminal state. It is deliberately not
  time-based, so it will not touch a genuinely long-running execution's hold.
- **A restart never resets a budget and never duplicates a reservation.** The
  period balance is derived by summing the ledger for the current `period_key`,
  not held in memory, so a process restart recomputes it exactly. And the
  partial unique index on `(budget_id, execution_id) WHERE status <> 'RELEASED'`
  means a retried claim after a crash cannot create a second live hold — the
  database refuses it. Neither property depends on anything surviving in a
  worker's memory, which is what makes recovery here uneventful.
- **The one thing a restore cannot reconstruct is an in-flight overshoot.** An
  execution that was mid-run when the snapshot was taken had a hold but not yet
  an actual; after a restore its hold is either swept (if its execution came
  back terminal) or still held (if it came back running). Neither is wrong, but
  the spend that execution had already incurred with the provider is not in
  `agent_executions` yet and will not be. That gap is bounded by one
  execution's cost and is the same gap ADR-0010 documents for the live system.
- **Real cost itself needs no special handling.** It lives on
  `agent_executions.cost_amount` with its `pricing_version`, written in the
  transaction that made the execution true, and this phase copies it nowhere.
  Restore the executions and the cost is correct; there is no rollup to rebuild
  and no aggregate that can be stale.
- **`model_pricing` must be restored with the executions.** Provenance lookups
  resolve a charge's `pricing_version` against it. Losing pricing rows does not
  change any recorded `cost_amount` — those are immutable — but it does make a
  past charge unexplainable, which is the §10 property gone.

**Phase 4.5's findings are the one Milestone 4 table you can safely lose**, and
saying so precisely matters more than it sounds, because the previous three
phases each added state you cannot.

- **`behavioral_findings` is derived, and it rebuilds.** Every finding is a
  deterministic function of `agent_executions`, `tool_calls` and the thresholds
  in code. Restore the executions and re-run the evaluation and you get
  byte-identical findings — that is what "deterministic" buys, and it is the
  practical difference between this table and `budget_reservations`, which
  *cannot* be recomputed because it records money that was actually spent.
- **So a restore that loses findings loses history, never behaviour.** Nothing
  reads a finding to make a decision: Phase 4.3's engine is the only thing that
  stops an execution and it does not consult them. Losing them costs an
  operator their record of what was noticed, not the platform its ability to
  notice again.
- **Re-running an evaluation after a restore cannot double-count.** The unique
  constraint on `(agent_id, signal_type, window_start, window_end)` means
  re-evaluating a window that survived the snapshot is a no-op rather than a
  duplicate. Sweeping the last few weeks of windows after a restore is a safe
  operation, not one that needs care.
- **The one thing that does not come back is a window whose executions did
  not.** A finding about a window that is now partly missing would recompute
  differently — correctly, from the data that exists — so a restored database
  can honestly disagree with a pre-restore finding about the same window. That
  is the derived plane behaving as designed, and it is why findings are not
  evidence in the sense `runtime_governance_decisions` and
  `budget_reservations` are.
- **Thresholds are code, not data.** `DEFAULT_THRESHOLDS` lives in
  `app/behavior/signals.py`; per-environment overrides ride on
  `Environment.policy`, which is restored with the environments. There is no
  separate configuration store to lose, and no restore can silently widen a
  threshold.

**Phase 4.6 (OpenTelemetry export) adds no durable state that a restore must
worry about, and the split is deliberate.**

- **The export buffer is ephemeral — dropped on restart, and never a phantom.**
  `BoundedSpanBuffer` is in-process memory holding spans on their way to a
  collector. A crash or restart loses whatever it held; a freshly-started
  dispatcher looks back only `TELEMETRY_EXPORT_SCHEDULER_LOOKBACK_SECONDS`
  (300s) for terminal executions and no further. So a restart can mean a few
  minutes of spans never reach the collector — that is the accepted cost of
  bounded memory (ADR-0011), and it is *observability* loss, never domain loss:
  the executions themselves are in `agent_executions`, and their traces can be
  re-assembled and re-exported at any time because export ids are deterministic.
- **Exporter health is in-process and resets cleanly.** `exporter_health` is a
  process-local counter set (last error, throughput, buffer depth), like the
  circuit breakers in `app.runtime.services`. A restart zeroes it, which is
  honest — the buffer it described is also gone. Nothing reads it to make a
  decision; it is a status surface only.
- **Export configuration is durable, and rides on state you already restore.**
  The per-environment `telemetry_export` block lives in `Environment.policy`
  JSONB, restored with the environments. The platform default is env vars
  (`TELEMETRY_EXPORT_*`), which belong with the deployment config, not the
  database. There is no separate export-config store to lose.
- **A restore cannot resurrect a stale collector target.** Because config is in
  `Environment.policy` and nowhere else, restoring the environments restores
  exactly the export destinations that were configured at snapshot time — no
  drift, no shadow copy.

> **Read "Encryption keys" below before trusting any snapshot.** A verified
> database dump plus a Git bundle is *not* sufficient to recover this platform's
> encrypted secrets, and the automated scripts do not cover the key material.

This project uses two independent recovery channels:

1. **Personal GitHub repository** for committed source history (keep it private):
   `https://github.com/Umair-zaka-ui/ai-agent-control-tower`
2. **A marked external or synced backup target** for verified PostgreSQL dumps,
   a portable Git bundle, local working-tree changes, manifests, and checksums.

Git alone cannot recover PostgreSQL rows. A local dump on the same computer is
also not disaster recovery. At least one completed snapshot must finish syncing
to another device/account or be copied to an external encrypted drive.

## Safety properties

The scripts under `scripts/backup/` are intentionally conservative:

- A destination must first contain the project-specific `.act-backup-target`
  marker. Backup and retention refuse arbitrary folders.
- Snapshots are built under a `.partial` name, verified, then atomically renamed.
- Git history is stored as a verified bundle; dirty tracked changes are stored as
  a binary patch; nonignored untracked files are copied separately.
- Backup aborts if Git state or verification row counts change during capture,
  avoiding a snapshot assembled from inconsistent moments.
- The database is stored as a PostgreSQL custom archive and fully parsed with
  `pg_restore` before the snapshot receives its `COMPLETE` marker.
- Every artifact receives a SHA-256 checksum.
- Restore refuses a nonempty database and never uses `--clean` or drops data.
- Pruning is opt-in, retains at least two completed snapshots, and only operates
  inside a correctly marked destination.
- `.env`, raw agent keys, development email tokens, virtual environments,
  `node_modules`, and browser tokens are excluded from ordinary snapshots.

No backup or restore script stops Docker containers or PostgreSQL services.

## Encryption keys — the one gap the scripts do not close

**`backend/.keys/` is not backed up by anything, and without it a restored
database's encrypted columns are permanently unreadable.** This was verified in
the 2026-08-14 pass, not assumed: `.keys/` and `backend/.keys/` are both listed
in `.gitignore`, so the Git bundle excludes them and `Backup-ControlTower.ps1`'s
"nonignored untracked files" copy skips them by definition; and
`Export-ControlTowerSecrets.ps1` archives a fixed list of three paths
(`backend/.env`, `frontend/.env`, `backups/seed-credentials.txt`) that does not
include them either. The directory currently holds 13,727 files on this machine.

Two distinct kinds of key material live there, both introduced after this guide
was first written:

| Path | Introduced | What is lost without it |
|---|---|---|
| `backend/.keys/model_credentials.key` (`MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH`) | Phase 5.7a.5 | The Fernet key for **every encrypted secret in the database** — per-organization model-provider credentials, connector credentials, connector OAuth access/refresh tokens, tool credentials, and identity-federation client secrets. The ciphertext restores fine and decrypts to nothing. |
| `backend/.keys/*.pem` (`SIGNING_KEY_PATH`) | Phase 5.2.4 | The Ed25519 **private** signing keys behind every version attestation. Public keys live in the database, so past signatures still verify; but the key cannot sign again, so rotation history and continuity of the signing identity are gone. |

If the key is absent at startup the platform generates and persists a **new**
one. Nothing fails loudly — new secrets encrypt and decrypt normally while every
pre-existing ciphertext silently becomes undecryptable. That is why this is
called out here rather than left to be discovered during an actual recovery.

Until the export script is extended to cover it, archive the directory manually
alongside a snapshot, to the same marked target, with the same AES-256 treatment
and a passphrase stored in a password manager:

```powershell
$sevenZip = 'C:\Program Files\7-Zip\7z.exe'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
& $sevenZip a -t7z -mx=9 -mhe=on -p `
  (Join-Path $target "control-tower-keys-$stamp.7z") `
  (Join-Path $repoRoot 'backend\.keys')
```

Preferred recovery behavior remains reissuing credentials rather than preserving
them (see below) — but that is a decision to make deliberately, not one to have
made for you by a backup that quietly omitted the keys.

On Windows systems that block unsigned local PowerShell scripts, enable them only
for the current terminal before running the commands below:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

This setting ends when that terminal closes; it does not weaken the machine-wide
execution policy. The scheduled task already uses the same process-scoped bypass.

## One-time target setup

Choose a location that survives loss of this computer. Examples are a synced
OneDrive folder (after confirming OneDrive is signed in and syncing) or a
BitLocker-encrypted external drive.

```powershell
$oneDrive = [Environment]::GetEnvironmentVariable('OneDrive')
if ([string]::IsNullOrWhiteSpace($oneDrive) -or
    -not (Test-Path -LiteralPath $oneDrive -PathType Container)) {
  throw 'OneDrive is not configured. Use an explicit external or synced folder instead.'
}
$target = Join-Path $oneDrive 'AI-Agent-Control-Tower-Recovery'
.\scripts\backup\Initialize-BackupTarget.ps1 -DestinationRoot $target
```

Do not use `C:\`, `D:\`, or a folder inside this repository merely because it
exists. On this machine both C: and D: are fixed drives, and the detected OneDrive
folder was not running at the time this guide was created. Verify the destination
really syncs or is physically separate before relying on it.

## Create and verify a snapshot

Run from the repository root:

```powershell
$oneDrive = [Environment]::GetEnvironmentVariable('OneDrive')
if ([string]::IsNullOrWhiteSpace($oneDrive) -or
    -not (Test-Path -LiteralPath $oneDrive -PathType Container)) {
  throw 'OneDrive is not configured. Use an explicit external or synced folder instead.'
}
$target = Join-Path $oneDrive 'AI-Agent-Control-Tower-Recovery'
.\scripts\backup\Backup-ControlTower.ps1 -DestinationRoot $target

$latest = Get-ChildItem $target -Directory |
  Where-Object Name -Match '^\d{8}T\d{6}Z$' |
  Sort-Object Name -Descending |
  Select-Object -First 1

.\scripts\backup\Verify-ControlTowerBackup.ps1 -SnapshotPath $latest.FullName
```

A normal snapshot contains no plaintext `.env` or one-time keys. Its database
archive is still sensitive because it contains password hashes, audit data, and
application rows. Protect the destination account with MFA, or use an encrypted
external drive.

## Secrets and exact credential continuity

Preferred recovery behavior is to generate a new database-role password and JWT
secret, force users to sign in again, and reissue agent API keys. This is safer
than preserving active credentials.

If exact continuity is required, manually create a separate AES-256 archive:

```powershell
.\scripts\backup\Export-ControlTowerSecrets.ps1 -DestinationRoot $target
```

7-Zip prompts for a passphrase and encrypts both contents and filenames. Save the
passphrase in a password manager that is available independently of this PC.
Never commit the passphrase or place an unencrypted recovery-key file beside the
archive. The encrypted export may contain:

- `backend/.env`
- `frontend/.env`
- `backups/seed-credentials.txt`

It does **not** contain `backend/.keys/` — see "Encryption keys" above, and
archive that directory separately if exact credential continuity is the goal.
Reissuing is the safer default precisely because it does not depend on that key
surviving.

The development outbox is excluded by default because it contains plaintext
verification/reset links. Include it only when truly needed:

```powershell
.\scripts\backup\Export-ControlTowerSecrets.ps1 `
  -DestinationRoot $target `
  -IncludeDevelopmentOutbox
```

## Daily automatic snapshots

After one manual snapshot verifies successfully, register a daily task:

```powershell
.\scripts\backup\Register-BackupTask.ps1 `
  -DestinationRoot $target `
  -DailyAt '02:00'
```

The task runs as the current user while signed in and starts later if the planned
time was missed. It does not delete old snapshots by default. To opt into bounded
retention later, register with `-Replace -EnablePruning -KeepCompletedSnapshots 14`.

Test the task before relying on it:

```powershell
Start-ScheduledTask -TaskName 'AI Agent Control Tower Backup'
Get-ScheduledTaskInfo -TaskName 'AI Agent Control Tower Backup'
```

Then verify the newest snapshot and confirm it appears through the sync provider
on another device or in its web interface.

## Recovery on a new Windows system

Install:

- Git
- PostgreSQL 17 (server and command-line tools) — 17.10 locally
- Python 3.13 — `backend/.venv` is on 3.13.14; the guide previously said 3.12,
  which is no longer installed on this machine
- Node.js 24 — v24.18.0 locally; the guide previously said 22 LTS
- 7-Zip (only when decrypting a secret archive, or the key archive above)
- Docker Desktop only if container deployment is required

`pip install -r requirements.txt` now pulls several dependencies added after this
guide was written — `boto3`, `pika`, `PyMySQL` (all pure-Python or wheel-only)
and, for SAML federation, `python3-saml` + `xmlsec` + `lxml`. The last three are
the only ones with a native component: `xmlsec` binds the `libxmlsec1` C library
and its wheel is tightly version-paired with `lxml`, so install from the pinned
`requirements.txt` rather than resolving those three loosely. If that pairing
fails on a new machine, it fails at install time and is obvious — no silent
degradation.

The snapshot carries its own verified scripts under `tools`, so recovery does not
depend on cloning GitHub first. Set the real snapshot path, then verify it:

```powershell
$snapshot = 'E:\AI-Agent-Control-Tower-Recovery\20260814T114925Z'
& (Join-Path $snapshot 'tools\Verify-ControlTowerBackup.ps1') `
  -SnapshotPath $snapshot
```

Read `manifest.json`, then create a new restricted PostgreSQL login and an empty
database owned by that login. Its PostgreSQL major version, encoding, collation,
and character type must match the manifest (or be a newer server with the same
locale). Do not run Alembic and do not seed it first. The repository destination
must not exist yet. Then restore with the script carried by the snapshot:

```powershell
& (Join-Path $snapshot 'tools\Restore-ControlTower.ps1') `
  -SnapshotPath $snapshot `
  -RepositoryDestination C:\Projects\ai-agent-control-tower-restored `
  -TargetDatabase ai_agent_control_tower_restored `
  -DatabaseUser ai_agent_control_tower_app
```

The script verifies checksums, clones the Git bundle, reapplies saved local work,
restores all saved Git refs and the original GitHub remote, validates the target
server/owner/locale and absence of user objects, restores in one transaction, and
compares the Alembic revision/table/data counts with the snapshot manifest. A
locale mismatch requires an explicit `-AllowLocaleMismatch` override and should
only be accepted after reviewing the database's sorting/index semantics.

After validation, create new ignored `.env` files or decrypt the separate secret
archive. From the restored repository:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\uvicorn.exe app.main:app --port 8002

cd ..\frontend
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd run dev
```

For a restored snapshot, `alembic current` must match the revision in
`manifest.json`. **Do not run `app.seed` against restored data.**

As of 2026-08-17 a healthy restore reports head `0043_distributed_scheduler` and
**123 tables**; the backend suite is `1,684 passed, 0 failed, 1 deselected` and
the frontend `297 passed`. The one deselected test is the `live_provider`-marked
Ollama check, excluded by default via `backend/pytest.ini` — a deselection, not a
failure, and it should stay deselected on a restored machine too.

## Docker: the PostgreSQL version mismatch is CLOSED (Phase 3.9)

**This was a real recovery gap and it is now fixed.** Until Phase 3.9 the base
Compose file declared PostgreSQL **16** and the database name
`agent_control_tower`, while every backup this project produces comes from
PostgreSQL **17** and the database `ai_agent_control_tower`. That is not
cosmetic: a logical dump from 17 will not restore into 16, and a 16 data
directory cannot be read by 17 — so the documented restore drill had no correct
container target to run against, and anyone who tried would have discovered it
during an incident.

`docker-compose.yml` now declares `postgres:17-alpine` and
`POSTGRES_DB: ai_agent_control_tower`, matching the live environment and the
backups. Asserted by a test (`test_ac12_compose_declares_the_postgres_version_
the_project_runs`) rather than left to drift again, alongside a second test that
checks the *running server* really is 17.

### ⚠️ Upgrading an existing checkout

`act_pgdata` is a PostgreSQL **major-version-specific** data directory. If you
ever started this stack on 16, PostgreSQL 17 will refuse to start against that
volume and the container will crash-loop on boot.

```bash
# Dump anything you still need FIRST -- this destroys the volume's contents.
docker compose down
docker volume rm <project>_act_pgdata     # e.g. ai-agent-control-tower_act_pgdata
docker compose up -d db
```

Deliberately **not** automated anywhere in this repository: it destroys data,
and a script that silently dropped a database volume on first run would be a
worse failure than the mismatch it fixed.

Still true, and still worth stating: do not copy Windows PostgreSQL data
directories into a container. Use `pg_dump`/`pg_restore` logical backups (what
`scripts/Restore-ControlTower.ps1` does), never a filesystem copy across
platforms.

## In-flight automated rollback (Phase 3.7)

Phase 3.7 added the platform's first piece of **automation that moves production
traffic on its own**, so it is also the first thing whose interrupted state
matters to a restore. It is designed around the same durable/ephemeral split
this guide already uses.

**Durable — restored with the database, and resumed automatically.**
A `rollback_events` row is written and committed with `status = 'IN_PROGRESS'`
*before* any traffic moves, and set to `COMPLETED` only after the traffic
allocation commits. A process that dies between those two points therefore
leaves a readable record of an intent that was formed but not finished, and it
survives a dump/restore like any other row.

Nothing needs to be done by hand. `RollbackService.resume_incomplete` runs at
the start of every trigger evaluation, finds such a row and completes it.
Re-applying is safe because Phase 3.4's traffic allocation declares a desired
end state rather than a delta — setting the same weights twice leaves the same
allocation — so **there is no half-applied traffic state a restore or a resume
could compound.**

**Ephemeral — recomputed, never restored.**
Health verdicts, threshold arithmetic, cooldown windows and the
"is this version on trial" check are all derived from the database on demand and
stored nowhere. They rebuild themselves on the first evaluation after a restart.

**What to check after restoring a snapshot**, before letting automation run:

```sql
SELECT id, deployment_id, trigger, status, created_at
FROM rollback_events
WHERE status = 'IN_PROGRESS'
ORDER BY created_at;
```

Rows here are rollbacks that were interrupted. They are resumed on the next
evaluation of their deployment, but on a *restored* system it is worth looking
first: a rollback interrupted by the same incident that caused the restore is
a strong signal about what was wrong.

**One deliberate restore-time caution.** Trigger policies
(`rollback_trigger_policies`) are restored along with everything else and are
active immediately. On a recovery system that is intentionally running with
stale or partial execution history, the health engine will read that history and
may reach conclusions that made no sense at the moment of restore. If you are
restoring into anything other than a faithful continuation of production,
disable automation first and re-enable it once real traffic is flowing:

```sql
UPDATE rollback_trigger_policies SET enabled = false;
```

Automation is opt-in by design — absent an enabled policy nothing fires — so a
freshly-seeded system has none of this to worry about. Note that the migration
deliberately creates no policies for existing tenants, precisely so that a
restore never silently arms automation nobody asked for.

## Scheduler state (Phase 3.8)

The distributed scheduler splits cleanly along the same durable/ephemeral line
as everything else here, and the split is the whole reason a crashed instance
is not a problem.

| State | Kind | On restore |
|---|---|---|
| `job_definitions` | **durable** | restored with the database; jobs resume being claimed |
| `job_runs` history | **durable** | restored; past outcomes are preserved |
| leases (`lease_owner`, `lease_expires_at`, `heartbeat_at`) | **ephemeral** | never honoured — a stale lease is *recovered*, not respected |

**A restored lease is never treated as a live owner.** After a restore, every
`lease_owner` in the database names a process that no longer exists. The
scheduler's recovery scan reclaims any non-terminal run whose lease has lapsed,
records where it came from in `recovered_from`, and re-runs it. Nothing needs to
be cleared by hand.

Re-running is safe because every registered handler is an idempotent
reconciliation — sweep current state, evaluate current gates — never an event
emitter. That is a deliberate design constraint, not a happy accident: a
database lease can guarantee exactly-once *dispatch*, but not exactly-once side
effects, so the handlers are written so a second run is harmless.

**Nothing starts a scheduler automatically.** Scheduler instances are separate
processes (`python -m app.scheduler.runner`); the API process deliberately does
not run one. A restored system therefore does no scheduled work at all until
you start an instance — which is usually what you want while verifying a
restore.

**What to check after restoring**, before starting any scheduler instance:

```sql
-- Jobs that were mid-flight when the snapshot was taken.
SELECT id, job_definition_id, status, attempt, lease_owner, lease_expires_at
FROM job_runs WHERE status IN ('CLAIMED', 'RUNNING') ORDER BY created_at;

-- What will start running the moment an instance is launched.
SELECT name, handler_key, enabled, next_run_at FROM job_definitions
WHERE enabled ORDER BY next_run_at;
```

The first query is informational — those rows recover themselves. The second is


## The Release Operations Center (Phase 3.10) — no recovery impact

Recorded explicitly rather than left unmentioned, because "the tracking files
were updated" should mean someone actually checked.

**Phase 3.10 changes nothing about recovery.** It added no table, no migration
and no state of its own: the Operations Center is twelve read-only views plus
four read-only endpoints over data the Phase 3.1–3.9 engines already own. After
a restore it shows whatever those engines contain — there is no cache to warm,
no projection to rebuild and nothing to reconcile.

The one operational note worth carrying over is not new either, and lives with
the fleet below: an in-flight rolling deployment will refuse to advance until
its cohorts have live workers again, so **start your workers before resuming
one**.

## The execution worker fleet (Phase 3.9)

Phase 3.9 moved agent execution onto independently-operable worker processes.
That changes what a restore has to reason about, and the split is the same one
everything else here follows.

| State | Kind | On restore |
|---|---|---|
| `agent_executions` | **durable** | the work itself; restored and re-claimable |
| `execution_attempts` | **durable** | attempt history preserved |
| `execution_locks` (`worker_id`, `expires_at`, `heartbeat_at`) | **ephemeral** | a lease; never honoured, always *recovered* |
| `worker_registrations` | **ephemeral** | describes a live OS process that no longer exists |

**A restored worker registration is never treated as live.** Every row in
`worker_registrations` after a restore names a process that is gone. Staleness
is a property of the data — `heartbeat_at` older than
`WORKER_STALE_AFTER_SECONDS` — so those rows stop counting toward fleet
capacity immediately, before any sweep runs. Nothing needs clearing by hand;
the workers rebuild the table by re-registering within one poll interval.

**A restored execution lease is never treated as a live owner.** Any execution
left `RUNNING` is recovered by `ExecutionWorkerService.reap_expired_locks`,
which applies the real retry policy — requeue if attempts remain, else
`DEAD_LETTERED` — and emits the terminal audit. Two clocks drive this
independently (worker staleness and lock expiry); whichever fires first, no
execution is left owned by a process that does not exist.

**Nothing starts a worker automatically.** Workers are separate processes
(`python -m app.workers.runner`); the API process deliberately runs none,
because an execution worker calls model providers and spends real money. A
restored system therefore executes no queued work at all until you start one —
which is usually what you want while verifying a restore.

**The honest limit on exactly-once.** A database lease guarantees exactly-once
*dispatch*, not exactly-once side effects. An execution interrupted after a
tool call committed but before its own result did will be retried, and that
tool will have been called twice. `ToolGatewayService` knows which tools are
idempotent and the retry policy never retries a policy denial — but if you are
restoring after a hard crash, expect at-least-once for non-idempotent tools and
check accordingly.

**What to check after restoring**, before starting any worker:

```sql
-- Executions that were mid-flight when the snapshot was taken.
SELECT e.id, e.status, e.attempt_count, l.worker_id, l.expires_at
FROM agent_executions e LEFT JOIN execution_locks l ON l.execution_id = e.id
WHERE e.status = 'RUNNING' ORDER BY e.started_at;

-- Work that will start the moment a worker is launched.
SELECT count(*) FROM agent_executions WHERE status = 'QUEUED';

-- Phantom fleet: rows describing processes that no longer exist.
SELECT worker_id, cohort, status, concurrency, heartbeat_at
FROM worker_registrations WHERE status <> 'STOPPED' ORDER BY heartbeat_at;
```

The first and third are informational — both recover themselves. The second
tells you how much work is about to begin.

**In-flight rolling deployments.** A `rollout_plans` row with `kind='ROLLING'`
is durable and resumes exactly where it stopped, but its `cohort_plan` records
the fleet *as it was when the rollout started*. After a restore that fleet does
not exist yet. The next advance will fail closed with `ROLLING_COHORT_INVALID`
until the named cohort has live workers again — which is the correct behaviour
(it refuses to move production traffic onto capacity that is not there), but it
means **start your workers before resuming a rolling deployment**, and start
them in the cohorts the plan names:

```sql
SELECT id, state, current_stage_index, cohort_plan -> 'steps'
FROM rollout_plans WHERE kind = 'ROLLING'
  AND state IN ('IN_PROGRESS', 'PAUSED');
```
the one to act on: if you are restoring into anything other than a faithful
continuation of production, disable the jobs before starting an instance, for
the same reason the rollback trigger policies should be disabled (§ above):

```sql
UPDATE job_definitions SET enabled = false;
```

Platform-level jobs (`organization_id IS NULL`) are seeded **disabled** and
`CONNECTOR_HEALTH_SCHEDULER_ENABLED` still defaults to false, so a
freshly-restored system has nothing armed unless someone armed it deliberately.

## What is intentionally rebuilt

These are not portable and should not be backed up:

- Python virtual environments
- `node_modules` and frontend build output
- caches, coverage artifacts, logs, and IDE configuration
- browser local storage and active session tokens
- PostgreSQL raw data directories and Docker Desktop VHDX files

Package locks, migrations, Dockerfiles, application code, and documentation are
already preserved by Git/GitHub and the verified Git bundle.

**`backend/.keys/` is not on this list.** It is gitignored, so it looks like the
same category of throwaway local state, and it is not — the platform will happily
regenerate a key and leave every existing ciphertext unreadable. Treat it as
secret material to be deliberately archived or deliberately abandoned, never as
something that rebuilds itself.
