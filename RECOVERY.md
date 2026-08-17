# Backup and system-migration guide

**Last verified 2026-08-14** against `main` at `5b33f42` (Phase 3.6). Facts that
matter for a restore, all re-checked live rather than carried forward: migration
head `0041_canary_rollout`, **119 tables**, PostgreSQL **17.10** locally,
`backend/.venv` on Python **3.13.14**, Node **v24.18.0**. Sections below that
name a version were corrected in this pass — the previous text said Python 3.12
and Node 22 LTS, and its `py -3.12 -m venv` command would now fail outright on
this machine.

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

As of 2026-08-14 a healthy restore reports head `0041_canary_rollout` and
**119 tables**; the backend suite is `1,575 passed, 0 failed, 1 deselected` and
the frontend `297 passed`. The one deselected test is the `live_provider`-marked
Ollama check, excluded by default via `backend/pytest.ini` — a deselection, not a
failure, and it should stay deselected on a restored machine too.

## Docker warning

The current logical backup is produced by PostgreSQL 17, while the repository's
base Compose file still declares PostgreSQL 16 and a different database name
(`agent_control_tower`). Do not copy Windows PostgreSQL data directories into a
container and do not point the restore script at that PostgreSQL 16 service.
Use a fresh PostgreSQL 17 target or create and review a dedicated Compose override
with seeding disabled before container-based recovery.

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
