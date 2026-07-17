[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SnapshotPath,

    [Parameter(Mandatory = $true)]
    [string]$RepositoryDestination,

    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase,

    [string]$DatabaseUser = 'ai_agent_control_tower_app',
    [string]$DatabaseHost = '127.0.0.1',
    [int]$DatabasePort = 5432,
    [string]$PgPassFile,
    [switch]$AllowCanonicalDatabaseName,
    [switch]$AllowLocaleMismatch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-PostgresTool {
    param([string]$Name)
    $command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $root = 'C:\Program Files\PostgreSQL'
    if (Test-Path -LiteralPath $root) {
        $versions = Get-ChildItem -LiteralPath $root -Directory | Sort-Object {
            $parsed = 0
            [int]::TryParse($_.Name, [ref]$parsed) | Out-Null
            $parsed
        } -Descending
        foreach ($version in $versions) {
            $candidate = Join-Path $version.FullName "bin\$Name.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    throw "Required PostgreSQL tool not found: $Name.exe"
}

function Test-ChildPath {
    param([string]$Parent, [string]$Child)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [System.IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)
}

$snapshot = (Resolve-Path -LiteralPath $SnapshotPath).Path
$verifyScript = Join-Path $PSScriptRoot 'Verify-ControlTowerBackup.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $verifyScript -SnapshotPath $snapshot
if ($LASTEXITCODE -ne 0) { throw 'Snapshot verification failed; nothing was restored.' }

$manifest = Get-Content -LiteralPath (Join-Path $snapshot 'manifest.json') -Raw | ConvertFrom-Json
$snapshotDatabase = [string]$manifest.database.name
if ($snapshotDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw 'Snapshot database name is unsafe.'
}
if ($TargetDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw 'TargetDatabase must use only letters, digits, and underscores and cannot start with a digit.'
}
if ($TargetDatabase -in @('postgres', 'template0', 'template1')) {
    throw "Refusing to restore into PostgreSQL system database: $TargetDatabase"
}
if (-not $AllowCanonicalDatabaseName -and $TargetDatabase -ieq $snapshotDatabase) {
    throw 'Refusing the canonical database name by default. Restore into a new name or pass -AllowCanonicalDatabaseName on a verified new system.'
}

$repositoryFull = [System.IO.Path]::GetFullPath($RepositoryDestination)
if (Test-Path -LiteralPath $repositoryFull) {
    throw "Repository destination must not already exist: $repositoryFull"
}
if (Test-ChildPath -Parent $snapshot -Child $repositoryFull) {
    throw 'Repository destination cannot be inside the recovery snapshot.'
}
$repositoryParent = Split-Path -Parent $repositoryFull
[System.IO.Directory]::CreateDirectory($repositoryParent) | Out-Null
$repositoryWork = "$repositoryFull.partial-$([Guid]::NewGuid().ToString('N'))"
$repositoryPromoted = $false

$bundle = Join-Path $snapshot 'source\ai-agent-control-tower.bundle'
$patch = Join-Path $snapshot 'source\working-tree.patch'
$untrackedRoot = Join-Path $snapshot 'source\untracked'

$psql = Find-PostgresTool 'psql'
$pgRestore = Find-PostgresTool 'pg_restore'
$databaseDirectory = [System.IO.Path]::GetFullPath((Join-Path $snapshot 'database'))
$dump = [System.IO.Path]::GetFullPath((Join-Path $databaseDirectory ($snapshotDatabase + '.dump')))
if (-not (Test-ChildPath -Parent $databaseDirectory -Child $dump) -or
    -not (Test-Path -LiteralPath $dump -PathType Leaf)) {
    throw 'Snapshot database archive path is unsafe or missing.'
}
$restoreVersion = (& $pgRestore --version).Trim()
if ($LASTEXITCODE -ne 0 -or $restoreVersion -notmatch '(\d+)(?:\.\d+)?') {
    throw 'Could not determine the pg_restore version.'
}
$restoreMajor = [int]$Matches[1]
$serverVersion = [string]$manifest.database.serverVersion
if ($serverVersion -notmatch '^(\d+)') { throw 'Snapshot PostgreSQL version is invalid.' }
$snapshotMajor = [int]$Matches[1]
if ($restoreMajor -lt $snapshotMajor) {
    throw "pg_restore $restoreMajor is older than the snapshot PostgreSQL major version $snapshotMajor. Install PostgreSQL $snapshotMajor or newer."
}

$passwordPointer = [IntPtr]::Zero
$previousPgPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'Process')
$previousPgPassFile = [Environment]::GetEnvironmentVariable('PGPASSFILE', 'Process')
try {
    if ($PgPassFile) {
        $resolvedPgPass = (Resolve-Path -LiteralPath $PgPassFile).Path
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        $env:PGPASSFILE = $resolvedPgPass
    }
    elseif (-not [string]::IsNullOrEmpty($previousPgPassword)) {
        # Respect an explicitly supplied process-level password without displaying it.
    }
    elseif (-not [string]::IsNullOrEmpty($previousPgPassFile)) {
        # Respect the caller's process-level pgpass file.
    }
    else {
        $securePassword = Read-Host "Password for PostgreSQL role $DatabaseUser" -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        Remove-Item Env:PGPASSFILE -ErrorAction SilentlyContinue
        $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    }

    $targetInfoSql = @"
WITH user_namespaces AS (
    SELECT oid FROM pg_namespace
    WHERE nspname = 'public'
       OR (nspname NOT IN ('pg_catalog', 'information_schema') AND nspname !~ '^pg_toast')
), extra_namespaces AS (
    SELECT oid FROM pg_namespace
    WHERE nspname <> 'public'
      AND nspname NOT IN ('pg_catalog', 'information_schema')
      AND nspname !~ '^pg_toast'
)
SELECT current_setting('server_version') || '|' ||
       pg_encoding_to_char(d.encoding) || '|' || d.datcollate || '|' || d.datctype || '|' ||
       pg_get_userbyid(d.datdba) || '|' ||
       ((SELECT count(*) FROM pg_class WHERE relnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_proc WHERE pronamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_type WHERE typnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_collation WHERE collnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_conversion WHERE connamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_ts_config WHERE cfgnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_ts_dict WHERE dictnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_ts_parser WHERE prsnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM pg_ts_template WHERE tmplnamespace IN (SELECT oid FROM user_namespaces)) +
        (SELECT count(*) FROM extra_namespaces) +
        (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql') +
        (SELECT count(*) FROM pg_event_trigger) +
        (SELECT count(*) FROM pg_foreign_data_wrapper) +
        (SELECT count(*) FROM pg_foreign_server) +
        (SELECT count(*) FROM pg_publication) +
        (SELECT count(*) FROM pg_largeobject_metadata))
FROM pg_database d WHERE d.datname = current_database()
"@
    $targetInfo = & $psql -X -h $DatabaseHost -p $DatabasePort -U $DatabaseUser -d $TargetDatabase -Atqc $targetInfoSql
    if ($LASTEXITCODE -ne 0 -or -not $targetInfo) {
        throw 'Cannot connect to the target database. Create an empty database owned by the application role first.'
    }
    $targetParts = ([string]$targetInfo).Trim() -split '\|'
    if ($targetParts.Count -ne 6) { throw 'Unexpected target database metadata shape.' }
    if ($targetParts[0] -notmatch '^(\d+)') { throw 'Target PostgreSQL version is invalid.' }
    $targetMajor = [int]$Matches[1]
    if ($targetMajor -lt $snapshotMajor) {
        throw "Target PostgreSQL $targetMajor is older than snapshot version $snapshotMajor."
    }
    if ($targetParts[1] -cne [string]$manifest.database.encoding) {
        throw "Target encoding $($targetParts[1]) does not match snapshot encoding $($manifest.database.encoding)."
    }
    if ($targetParts[2] -cne [string]$manifest.database.collation -or
        $targetParts[3] -cne [string]$manifest.database.characterType) {
        $localeMessage = "Target locale $($targetParts[2])/$($targetParts[3]) does not match snapshot locale $($manifest.database.collation)/$($manifest.database.characterType)."
        if (-not $AllowLocaleMismatch) { throw $localeMessage + ' Recreate the empty database with the matching locale or explicitly pass -AllowLocaleMismatch.' }
        Write-Warning $localeMessage
    }
    if ($targetParts[4] -cne $DatabaseUser) {
        throw "Target database owner is $($targetParts[4]); expected $DatabaseUser."
    }
    if ([int64]$targetParts[5] -ne 0) {
        throw "Target database is not empty: $TargetDatabase ($($targetParts[5]) user object(s) found)."
    }

    # Build source recovery under a sibling partial path. It is promoted only
    # after the database restore and verification both succeed.
    & git clone $bundle $repositoryWork
    if ($LASTEXITCODE -ne 0) { throw 'Repository clone from bundle failed.' }

    [string[]]$bundleHeads = @(& git bundle list-heads $bundle)
    if ($LASTEXITCODE -ne 0) { throw 'Could not enumerate refs from the Git bundle.' }
    foreach ($bundleHead in $bundleHeads) {
        if ($bundleHead -match '^([0-9a-fA-F]{40,64}) (refs/.+)$') {
            $objectId = $Matches[1]
            $refName = $Matches[2]
            & git -C $repositoryWork check-ref-format $refName
            if ($LASTEXITCODE -ne 0) { throw "Unsafe ref in bundle: $refName" }
            & git -C $repositoryWork update-ref $refName $objectId
            if ($LASTEXITCODE -ne 0) { throw "Could not restore Git ref: $refName" }
        }
    }

    if ((Test-Path -LiteralPath $patch) -and (Get-Item -LiteralPath $patch).Length -gt 0) {
        & git -C $repositoryWork apply --check --binary $patch
        if ($LASTEXITCODE -ne 0) { throw 'Working-tree patch preflight failed.' }
        & git -C $repositoryWork apply --binary $patch
        if ($LASTEXITCODE -ne 0) { throw 'Working-tree patch application failed.' }
    }

    if (Test-Path -LiteralPath $untrackedRoot) {
        $baseUri = New-Object System.Uri(($untrackedRoot.TrimEnd('\') + '\'))
        foreach ($file in (Get-ChildItem -LiteralPath $untrackedRoot -Recurse -File)) {
            $fileUri = New-Object System.Uri($file.FullName)
            $relative = [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($fileUri).ToString()).Replace('/', '\')
            $target = Join-Path $repositoryWork $relative
            if (Test-Path -LiteralPath $target) { throw "Untracked-file restore collision: $relative" }
            [System.IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target
        }
    }

    $originalRemote = [string]$manifest.source.remote
    if ([string]::IsNullOrWhiteSpace($originalRemote)) { throw 'Snapshot source remote is missing.' }
    & git -C $repositoryWork remote set-url origin $originalRemote
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the original Git remote URL.' }

    & $pgRestore -h $DatabaseHost -p $DatabasePort -U $DatabaseUser -d $TargetDatabase --no-owner --no-privileges --exit-on-error --single-transaction $dump
    if ($LASTEXITCODE -ne 0) { throw 'Database restore failed.' }

    $verifySql = "SELECT (SELECT version_num FROM alembic_version) || '|' || (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE') || '|' || (SELECT count(*) FROM organizations) || '|' || (SELECT count(*) FROM users) || '|' || (SELECT count(*) FROM agents) || '|' || (SELECT count(*) FROM agent_api_keys) || '|' || (SELECT count(*) FROM permissions) || '|' || (SELECT count(*) FROM policies) || '|' || (SELECT count(*) FROM permission_groups) || '|' || (SELECT count(*) FROM rbac_permissions) || '|' || (SELECT count(*) FROM roles) || '|' || (SELECT count(*) FROM role_hierarchy) || '|' || (SELECT count(*) FROM user_roles) || '|' || (SELECT count(*) FROM role_permissions)"
    $actual = & $psql -X -h $DatabaseHost -p $DatabasePort -U $DatabaseUser -d $TargetDatabase -Atqc $verifySql
    if ($LASTEXITCODE -ne 0) { throw 'Post-restore database verification query failed.' }
    $expected = "$($manifest.database.alembicRevision)|$($manifest.database.publicTables)|$($manifest.database.organizations)|$($manifest.database.users)|$($manifest.database.agents)|$($manifest.database.agentApiKeys)|$($manifest.database.permissions)|$($manifest.database.policies)|$($manifest.database.permissionGroups)|$($manifest.database.rbacPermissions)|$($manifest.database.roles)|$($manifest.database.roleHierarchy)|$($manifest.database.userRoles)|$($manifest.database.rolePermissions)"
    if ($actual -ne $expected) { throw "Restored database does not match manifest. Expected $expected, got $actual" }

    Move-Item -LiteralPath $repositoryWork -Destination $repositoryFull
    $repositoryPromoted = $true
}
catch {
    if (-not $repositoryPromoted -and (Test-Path -LiteralPath $repositoryWork)) {
        Write-Warning "Restore failed; partial repository retained for inspection: $repositoryWork"
    }
    throw
}
finally {
    if ($null -eq $previousPgPassword) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    else {
        [Environment]::SetEnvironmentVariable('PGPASSWORD', $previousPgPassword, 'Process')
    }
    if ($null -eq $previousPgPassFile) {
        Remove-Item Env:PGPASSFILE -ErrorAction SilentlyContinue
    }
    else {
        [Environment]::SetEnvironmentVariable('PGPASSFILE', $previousPgPassFile, 'Process')
    }
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}

Write-Host 'Control Tower restore completed successfully.'
Write-Host "Repository: $repositoryFull"
Write-Host "Database: $TargetDatabase"
Write-Host 'Secrets were intentionally not restored. Create fresh .env files or decrypt the separate secret archive.'
Write-Host 'Do not run the demo seed against this restored database.'
