# Backup and system-migration guide

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
- PostgreSQL 17 (server and command-line tools)
- Python 3.12
- Node.js 22 LTS
- 7-Zip (only when decrypting a secret archive)
- Docker Desktop only if container deployment is required

The snapshot carries its own verified scripts under `tools`, so recovery does not
depend on cloning GitHub first. Set the real snapshot path, then verify it:

```powershell
$snapshot = 'E:\AI-Agent-Control-Tower-Recovery\20260717T114925Z'
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
py -3.12 -m venv .venv
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
