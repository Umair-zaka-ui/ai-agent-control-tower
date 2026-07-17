[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SnapshotPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RelativePath {
    param([string]$BasePath, [string]$FullPath)
    $baseUri = New-Object System.Uri(($BasePath.TrimEnd('\') + '\'))
    $fileUri = New-Object System.Uri($FullPath)
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($fileUri).ToString()).Replace('/', '\')
}

function Test-ChildPath {
    param([string]$Parent, [string]$Child)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [System.IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)
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

$snapshot = (Resolve-Path -LiteralPath $SnapshotPath).Path
$complete = Join-Path $snapshot 'COMPLETE'
$manifestPath = Join-Path $snapshot 'manifest.json'
$checksumsPath = Join-Path $snapshot 'SHA256SUMS.txt'

foreach ($required in @($complete, $manifestPath, $checksumsPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Incomplete snapshot; missing $required" }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.project -ne 'ai-agent-control-tower' -or $manifest.schemaVersion -ne 1) {
    throw 'Snapshot manifest is invalid or belongs to another project.'
}
$snapshotDatabase = [string]$manifest.database.name
if ($snapshotDatabase -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw 'Snapshot database name is unsafe.'
}

$lines = Get-Content -LiteralPath $checksumsPath
$verified = 0
$listedArtifacts = @{}
foreach ($line in $lines) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '^([a-fA-F0-9]{64})  (.+)$') { throw "Invalid checksum line: $line" }
    $expected = $Matches[1].ToUpperInvariant()
    $relative = $Matches[2].Replace('/', '\')
    if ([System.IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Unsafe checksum path: $relative"
    }
    $file = [System.IO.Path]::GetFullPath((Join-Path $snapshot $relative))
    $snapshotPrefix = $snapshot.TrimEnd('\') + '\'
    if (-not $file.StartsWith($snapshotPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Checksum path escaped snapshot: $relative"
    }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Artifact missing: $relative" }
    if ($listedArtifacts.ContainsKey($relative)) { throw "Duplicate checksum entry: $relative" }
    $listedArtifacts[$relative] = $true
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($actual -ne $expected) { throw "Checksum mismatch: $relative" }
    $verified++
}
if ($verified -lt 5) { throw 'Snapshot contains unexpectedly few checksummed artifacts.' }

$actualArtifacts = @(Get-ChildItem -LiteralPath $snapshot -Recurse -File | Where-Object {
    $_.FullName -ne $checksumsPath -and $_.FullName -ne $complete
})
foreach ($artifact in $actualArtifacts) {
    $relative = Get-RelativePath -BasePath $snapshot -FullPath $artifact.FullName
    if (-not $listedArtifacts.ContainsKey($relative)) {
        throw "Artifact has no checksum entry: $relative"
    }
}
if ($actualArtifacts.Count -ne $verified) {
    throw "Checksum inventory mismatch: listed $verified artifacts, found $($actualArtifacts.Count)"
}

$bundle = Join-Path $snapshot 'source\ai-agent-control-tower.bundle'
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$bundleVerifyRepo = [System.IO.Path]::GetFullPath((Join-Path $tempRoot ("act-bundle-verify-" + [Guid]::NewGuid().ToString('N'))))
if (-not $bundleVerifyRepo.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Computed Git verification path escaped the temporary directory.'
}
try {
    & git init --bare $bundleVerifyRepo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Temporary Git verification repository creation failed.' }
    & git -C $bundleVerifyRepo bundle verify $bundle | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Git bundle verification failed.' }
}
finally {
    if (Test-Path -LiteralPath $bundleVerifyRepo) {
        Remove-Item -LiteralPath $bundleVerifyRepo -Recurse -Force
    }
}

$databaseDirectory = [System.IO.Path]::GetFullPath((Join-Path $snapshot 'database'))
$dump = [System.IO.Path]::GetFullPath((Join-Path $databaseDirectory ($snapshotDatabase + '.dump')))
if (-not (Test-ChildPath -Parent $databaseDirectory -Child $dump) -or
    -not (Test-Path -LiteralPath $dump -PathType Leaf)) {
    throw 'Snapshot database archive path is unsafe or missing.'
}
$pgRestore = Find-PostgresTool 'pg_restore'
& $pgRestore --list $dump | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL archive listing failed.' }
& $pgRestore --file=NUL --no-owner --no-privileges $dump
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL full archive parse failed.' }

Write-Host 'Recovery snapshot verification: PASS'
Write-Host "Snapshot: $snapshot"
Write-Host "Artifacts verified: $verified"
Write-Host "Git commit: $($manifest.source.commit)"
Write-Host "Database revision: $($manifest.database.alembicRevision)"
Write-Host "Public tables: $($manifest.database.publicTables)"
