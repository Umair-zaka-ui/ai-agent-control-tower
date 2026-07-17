[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [int]$KeepCompletedSnapshots = 14,

    [switch]$Prune,

    [switch]$AllowInsideRepository
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$utf8 = New-Object System.Text.UTF8Encoding($false)
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$destination = (Resolve-Path -LiteralPath $DestinationRoot).Path
$repoPrefix = $repoRoot.TrimEnd('\') + '\'

function Test-ChildPath {
    param([string]$Parent, [string]$Child)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [System.IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-RelativePath {
    param([string]$BasePath, [string]$FullPath)
    $baseUri = New-Object System.Uri(($BasePath.TrimEnd('\') + '\'))
    $fileUri = New-Object System.Uri($FullPath)
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($fileUri).ToString()).Replace('/', '\')
}

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

if (-not $AllowInsideRepository -and
    ($destination -eq $repoRoot -or $destination.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw 'Refusing a backup destination inside the repository. Initialize an external/synced target instead.'
}

$marker = Join-Path $destination '.act-backup-target'
if (-not (Test-Path -LiteralPath $marker)) {
    throw "Destination is not initialized: $marker. Run Initialize-BackupTarget.ps1 first."
}
$markerData = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($markerData.project -ne 'ai-agent-control-tower' -or $markerData.schemaVersion -ne 1) {
    throw 'Backup target marker is invalid or belongs to another project.'
}

$lockPath = Join-Path $destination '.backup.lock'
$lockStream = $null
$partial = $null

try {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch {
        throw 'Another Control Tower backup appears to be running for this destination.'
    }

    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $final = Join-Path $destination $stamp
    $partial = "$final.partial"
    if ((Test-Path -LiteralPath $final) -or (Test-Path -LiteralPath $partial)) {
        throw "Snapshot path already exists: $stamp"
    }
    if (-not (Test-ChildPath -Parent $destination -Child $partial)) {
        throw 'Computed snapshot path escaped the marked destination.'
    }

    $sourceDir = Join-Path $partial 'source'
    $databaseDir = Join-Path $partial 'database'
    $toolsDir = Join-Path $partial 'tools'
    [System.IO.Directory]::CreateDirectory($sourceDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($databaseDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($toolsDir) | Out-Null

    Write-Host "Creating recovery snapshot $stamp"

    # Source history: a portable bundle plus exact working-tree state.
    if (Test-Path -LiteralPath (Join-Path $repoRoot '.gitmodules')) {
        throw 'Git submodules are present. Add an explicit submodule backup strategy before creating a snapshot.'
    }
    [string[]]$attributeFiles = @(& git -C $repoRoot ls-files -- '*.gitattributes')
    if ($LASTEXITCODE -ne 0) { throw 'Git attribute inventory failed' }
    foreach ($attributeFile in $attributeFiles) {
        $attributePath = Join-Path $repoRoot $attributeFile
        if (Select-String -LiteralPath $attributePath -Pattern 'filter\s*=\s*lfs' -Quiet) {
            throw "Git LFS configuration detected in $attributeFile. Add an explicit LFS object backup strategy first."
        }
    }

    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'git HEAD lookup failed' }
    $branch = (& git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'git branch lookup failed' }
    [string[]]$gitStatus = @(& git -C $repoRoot status --porcelain=v2 --branch)
    if ($LASTEXITCODE -ne 0) { throw 'git status failed' }
    [string]$untrackedRaw = ''
    $untrackedOutput = & git -C $repoRoot -c core.quotePath=false ls-files -z --others --exclude-standard
    if ($LASTEXITCODE -ne 0) { throw 'untracked-file inventory failed' }
    if ($null -ne $untrackedOutput) { $untrackedRaw = [string]$untrackedOutput }
    [string[]]$untracked = @()
    if ($untrackedRaw.Length -gt 0) {
        $untracked = @($untrackedRaw -split "`0" | Where-Object { $_.Length -gt 0 })
    }

    $bundle = Join-Path $sourceDir 'ai-agent-control-tower.bundle'
    & git -C $repoRoot bundle create $bundle --all
    if ($LASTEXITCODE -ne 0) { throw 'git bundle creation failed' }
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        [string[]]$bundleVerification = @(& git -C $repoRoot bundle verify $bundle 2>&1 | ForEach-Object { $_.ToString() })
        $bundleVerificationExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($bundleVerificationExitCode -ne 0) { throw 'git bundle verification failed' }
    [System.IO.File]::WriteAllLines(
        (Join-Path $sourceDir 'bundle-verification.txt'),
        [string[]]$bundleVerification,
        $utf8
    )

    [System.IO.File]::WriteAllLines((Join-Path $sourceDir 'git-status.txt'), $gitStatus, $utf8)

    $patchPath = Join-Path $sourceDir 'working-tree.patch'
    & git -C $repoRoot diff HEAD --binary --full-index "--output=$patchPath"
    if ($LASTEXITCODE -ne 0) { throw 'working-tree patch creation failed' }

    [string[]]$untrackedInventory = @($untracked | ForEach-Object { ConvertTo-Json $_ -Compress })
    [System.IO.File]::WriteAllLines((Join-Path $sourceDir 'untracked-files.txt'), $untrackedInventory, $utf8)
    if ($untracked.Count -gt 0) {
        $untrackedRoot = Join-Path $sourceDir 'untracked'
        foreach ($relative in $untracked) {
            if ([System.IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
                throw "Unsafe untracked path: $relative"
            }
            if ($relative -match '(^|[\\/])\.env($|\.)' -or $relative -match '\.(pem|pfx|p12|key)$') {
                throw "Potential secret is nonignored and will not be copied: $relative"
            }
            $sourceFile = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $relative))
            if (-not (Test-ChildPath -Parent $repoRoot -Child $sourceFile)) {
                throw "Untracked path escaped repository: $relative"
            }
            $targetFile = Join-Path $untrackedRoot $relative
            [System.IO.Directory]::CreateDirectory((Split-Path -Parent $targetFile)) | Out-Null
            Copy-Item -LiteralPath $sourceFile -Destination $targetFile
        }
    }

    # Re-read source state and content so a concurrent edit/commit cannot create
    # a bundle, patch, and untracked tree that describe different moments.
    $headAfterCapture = (& git -C $repoRoot rev-parse HEAD).Trim()
    [string[]]$gitStatusAfterCapture = @(& git -C $repoRoot status --porcelain=v2 --branch)
    if ($LASTEXITCODE -ne 0) { throw 'post-capture git status failed' }
    [string]$untrackedRawAfterCapture = ''
    $untrackedOutputAfterCapture = & git -C $repoRoot -c core.quotePath=false ls-files -z --others --exclude-standard
    if ($LASTEXITCODE -ne 0) { throw 'post-capture untracked-file inventory failed' }
    if ($null -ne $untrackedOutputAfterCapture) { $untrackedRawAfterCapture = [string]$untrackedOutputAfterCapture }
    if ($headAfterCapture -cne $head -or
        ($gitStatusAfterCapture -join "`0") -cne ($gitStatus -join "`0") -or
        $untrackedRawAfterCapture -cne $untrackedRaw) {
        throw 'Git repository state changed while source artifacts were being captured; retry the backup.'
    }

    $patchCheck = Join-Path $sourceDir 'working-tree.postcheck.patch'
    & git -C $repoRoot diff HEAD --binary --full-index "--output=$patchCheck"
    if ($LASTEXITCODE -ne 0) { throw 'working-tree patch stability check failed' }
    if ((Get-FileHash -LiteralPath $patchCheck -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $patchPath -Algorithm SHA256).Hash) {
        throw 'Tracked file content changed while the source patch was being captured; retry the backup.'
    }
    Remove-Item -LiteralPath $patchCheck -Force

    if ($untracked.Count -gt 0) {
        foreach ($relative in $untracked) {
            $sourceFile = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $relative))
            $capturedFile = Join-Path (Join-Path $sourceDir 'untracked') $relative
            if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf) -or
                (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash -ne
                (Get-FileHash -LiteralPath $capturedFile -Algorithm SHA256).Hash) {
                throw "Untracked file changed while being captured: $relative"
            }
        }
    }

    # Parse the ignored local connection URL without printing it.
    $envFile = Join-Path $repoRoot 'backend\.env'
    if (-not (Test-Path -LiteralPath $envFile)) { throw 'backend/.env is missing' }
    $databaseLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
    if (-not $databaseLine) { throw 'DATABASE_URL is missing from backend/.env' }
    $databaseUrl = $databaseLine.Substring('DATABASE_URL='.Length).Trim()
    $normalizedUrl = $databaseUrl -replace '^postgresql\+psycopg2:', 'postgresql:'
    $uri = New-Object System.Uri($normalizedUrl)
    $colon = $uri.UserInfo.IndexOf(':')
    if ($colon -lt 1) { throw 'DATABASE_URL user/password section is invalid' }
    $databaseUser = [System.Uri]::UnescapeDataString($uri.UserInfo.Substring(0, $colon))
    $databasePassword = [System.Uri]::UnescapeDataString($uri.UserInfo.Substring($colon + 1))
    $databaseHost = $uri.Host
    $databasePort = if ($uri.IsDefaultPort) { 5432 } else { $uri.Port }
    $databaseName = $uri.AbsolutePath.TrimStart('/')
    if (-not $databaseName) { throw 'DATABASE_URL database name is missing' }
    if ($databaseName -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw 'DATABASE_URL database name contains unsupported characters for a portable snapshot.'
    }

    $pgDump = Find-PostgresTool 'pg_dump'
    $pgRestore = Find-PostgresTool 'pg_restore'
    $psql = Find-PostgresTool 'psql'
    $databaseDump = Join-Path $databaseDir "$databaseName.dump"
    $archiveToc = Join-Path $databaseDir 'archive-toc.txt'

    $previousPgPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'Process')
    $env:PGPASSWORD = $databasePassword
    try {
        $dbInfoSql = "SELECT current_setting('server_version') || '|' || current_database() || '|' || current_user || '|' || pg_encoding_to_char(encoding) || '|' || datcollate || '|' || datctype FROM pg_database WHERE datname=current_database()"
        $dbInfo = & $psql -X -h $databaseHost -p $databasePort -U $databaseUser -d $databaseName -Atqc $dbInfoSql
        if ($LASTEXITCODE -ne 0 -or -not $dbInfo) { throw 'database metadata query failed' }

        $countsSql = "SELECT (SELECT version_num FROM alembic_version) || '|' || (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE') || '|' || (SELECT count(*) FROM organizations) || '|' || (SELECT count(*) FROM users) || '|' || (SELECT count(*) FROM agents) || '|' || (SELECT count(*) FROM agent_api_keys) || '|' || (SELECT count(*) FROM permissions) || '|' || (SELECT count(*) FROM policies) || '|' || (SELECT count(*) FROM permission_groups) || '|' || (SELECT count(*) FROM rbac_permissions) || '|' || (SELECT count(*) FROM roles) || '|' || (SELECT count(*) FROM role_hierarchy) || '|' || (SELECT count(*) FROM user_roles) || '|' || (SELECT count(*) FROM role_permissions)"
        $countsBefore = & $psql -X -h $databaseHost -p $databasePort -U $databaseUser -d $databaseName -Atqc $countsSql
        if ($LASTEXITCODE -ne 0 -or -not $countsBefore) { throw 'database verification-count query failed' }

        & $pgDump -h $databaseHost -p $databasePort -U $databaseUser -d $databaseName -Fc -Z 9 --no-owner --no-privileges --lock-wait-timeout=60s --file=$databaseDump
        if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
        if ((Get-Item -LiteralPath $databaseDump).Length -le 0) { throw 'database archive is empty' }

        $countsAfter = & $psql -X -h $databaseHost -p $databasePort -U $databaseUser -d $databaseName -Atqc $countsSql
        if ($LASTEXITCODE -ne 0 -or -not $countsAfter) { throw 'post-dump database verification-count query failed' }
        if (([string]$countsAfter).Trim() -cne ([string]$countsBefore).Trim()) {
            throw 'Database verification counts changed during pg_dump; retry when writes are quiet.'
        }
        $counts = $countsAfter

        $toc = [string[]](& $pgRestore --list $databaseDump)
        if ($LASTEXITCODE -ne 0) { throw 'pg_restore archive listing failed' }
        [System.IO.File]::WriteAllLines($archiveToc, $toc, $utf8)
        & $pgRestore --file=NUL --no-owner --no-privileges $databaseDump
        if ($LASTEXITCODE -ne 0) { throw 'full database archive parse failed' }
    }
    finally {
        if ($null -eq $previousPgPassword) {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable('PGPASSWORD', $previousPgPassword, 'Process')
        }
        $databasePassword = $null
    }

    # Keep restore tooling next to the artifacts, even before the bundle is cloned.
    Copy-Item -Path (Join-Path $PSScriptRoot '*') -Destination $toolsDir -Recurse -Force

    $secretsInventory = @(
        'Secrets intentionally excluded from this ordinary recovery snapshot:',
        '- backend/.env (database/JWT/SMTP configuration)',
        '- frontend/.env (local build configuration)',
        '- backups/seed-credentials.txt (one-time raw agent API keys)',
        '- backend/var/dev-outbox.log (plaintext development email links/tokens)',
        '',
        'Store required values in a password manager or export them separately with Export-ControlTowerSecrets.ps1.',
        'On a new system, rotating JWT/database credentials and reissuing agent keys is safer than preserving active sessions.'
    )
    [System.IO.File]::WriteAllLines((Join-Path $partial 'secrets-inventory.txt'), $secretsInventory, $utf8)

    $remote = (& git -C $repoRoot remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'git origin lookup failed' }
    $remoteUri = $null
    if ([System.Uri]::TryCreate($remote, [System.UriKind]::Absolute, [ref]$remoteUri) -and $remoteUri.UserInfo) {
        $remoteBuilder = New-Object System.UriBuilder($remoteUri)
        $remoteBuilder.UserName = ''
        $remoteBuilder.Password = ''
        $remote = $remoteBuilder.Uri.AbsoluteUri
    }
    [string[]]$dirtyLines = @($gitStatus | Where-Object { -not $_.StartsWith('#') })
    $dbParts = ([string]$dbInfo).Trim() -split '\|'
    $countParts = ([string]$counts).Trim() -split '\|'
    if ($dbParts.Count -ne 6 -or $countParts.Count -ne 14) {
        throw 'Unexpected database manifest shape'
    }

    $pythonExe = Join-Path $repoRoot 'backend\venv\Scripts\python.exe'
    $pythonVersion = if (Test-Path -LiteralPath $pythonExe) { (& $pythonExe --version 2>&1).Trim() } else { 'not installed' }
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $nodeVersion = if ($nodeCommand) { (& $nodeCommand.Source --version).Trim() } else { 'not installed' }

    $manifest = [ordered]@{
        schemaVersion = 1
        project       = 'ai-agent-control-tower'
        createdAtUtc  = [DateTime]::UtcNow.ToString('o')
        source        = [ordered]@{
            commit       = $head
            branch       = $branch
            remote       = $remote
            dirty        = ($dirtyLines.Count -gt 0)
            untracked    = $untracked.Count
            gitVersion   = (& git --version).Trim()
        }
        database      = [ordered]@{
            serverVersion     = $dbParts[0]
            name              = $dbParts[1]
            role              = $dbParts[2]
            encoding          = $dbParts[3]
            collation         = $dbParts[4]
            characterType     = $dbParts[5]
            alembicRevision   = $countParts[0]
            publicTables      = [int]$countParts[1]
            organizations     = [int]$countParts[2]
            users             = [int]$countParts[3]
            agents            = [int]$countParts[4]
            agentApiKeys      = [int]$countParts[5]
            permissions       = [int]$countParts[6]
            policies          = [int]$countParts[7]
            permissionGroups  = [int]$countParts[8]
            rbacPermissions   = [int]$countParts[9]
            roles             = [int]$countParts[10]
            roleHierarchy     = [int]$countParts[11]
            userRoles         = [int]$countParts[12]
            rolePermissions   = [int]$countParts[13]
            dumpTool          = (& $pgDump --version).Trim()
        }
        runtime       = [ordered]@{
            python = $pythonVersion
            node   = $nodeVersion
            recommendedPython = '3.12'
            recommendedNode   = '22 LTS'
            recommendedPostgres = '17'
        }
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $partial 'manifest.json'),
        ($manifest | ConvertTo-Json -Depth 8),
        $utf8
    )

    $checksumFile = Join-Path $partial 'SHA256SUMS.txt'
    $checksumLines = New-Object System.Collections.Generic.List[string]
    $artifactFiles = Get-ChildItem -LiteralPath $partial -Recurse -File | Sort-Object FullName
    foreach ($file in $artifactFiles) {
        if ($file.FullName -eq $checksumFile) { continue }
        $relative = (Get-RelativePath -BasePath $partial -FullPath $file.FullName).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $checksumLines.Add("$hash  $relative")
    }
    [System.IO.File]::WriteAllLines($checksumFile, $checksumLines, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $partial 'COMPLETE'), "verified $stamp" + [Environment]::NewLine, $utf8)

    Move-Item -LiteralPath $partial -Destination $final
    $partial = $null
    Write-Host "Recovery snapshot completed: $final"

    if ($Prune) {
        if ($KeepCompletedSnapshots -lt 2) { throw 'KeepCompletedSnapshots must be at least 2 when pruning' }
        $completed = Get-ChildItem -LiteralPath $destination -Directory |
            Where-Object { $_.Name -match '^\d{8}T\d{6}Z$' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'COMPLETE')) } |
            Sort-Object Name -Descending
        $expired = @($completed | Select-Object -Skip $KeepCompletedSnapshots)
        foreach ($snapshot in $expired) {
            if (Test-Path -LiteralPath (Join-Path $snapshot.FullName 'KEEP')) { continue }
            if (($snapshot.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing to prune a reparse-point snapshot directory: $($snapshot.FullName)"
            }
            if (-not (Test-ChildPath -Parent $destination -Child $snapshot.FullName)) {
                throw "Refusing to prune path outside destination: $($snapshot.FullName)"
            }
            Remove-Item -LiteralPath $snapshot.FullName -Recurse -Force
            Write-Host "Pruned verified snapshot: $($snapshot.Name)"
        }
    }
}
catch {
    if ($partial -and (Test-Path -LiteralPath $partial)) {
        Write-Warning "Backup failed; partial snapshot retained for inspection: $partial"
    }
    throw
}
finally {
    if ($lockStream) { $lockStream.Dispose() }
    if (Test-Path -LiteralPath $lockPath) {
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}
