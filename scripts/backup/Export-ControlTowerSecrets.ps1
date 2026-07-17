[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [switch]$IncludeDevelopmentOutbox
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$destination = (Resolve-Path -LiteralPath $DestinationRoot).Path
$repoPrefix = $repoRoot.TrimEnd('\') + '\'
if ($destination -eq $repoRoot -or $destination.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Encrypted secret exports must be written to an external or synced target, never inside the repository.'
}
$marker = Join-Path $destination '.act-backup-target'
if (-not (Test-Path -LiteralPath $marker)) {
    throw 'Destination is not an initialized Control Tower backup target.'
}
$markerData = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($markerData.project -ne 'ai-agent-control-tower' -or $markerData.schemaVersion -ne 1) {
    throw 'Backup marker is invalid or belongs to another project.'
}

$sevenZipCandidates = @(
    'C:\Program Files\7-Zip\7z.exe',
    'C:\Program Files (x86)\7-Zip\7z.exe'
)
$sevenZip = $sevenZipCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $sevenZip) { throw '7-Zip is required for AES-256 secret export.' }

$secretFiles = New-Object System.Collections.Generic.List[string]
foreach ($relative in @('backend\.env', 'frontend\.env', 'backups\seed-credentials.txt')) {
    $path = Join-Path $repoRoot $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) { $secretFiles.Add($relative) }
}
if ($IncludeDevelopmentOutbox) {
    $outbox = Join-Path $repoRoot 'backend\var\dev-outbox.log'
    if (Test-Path -LiteralPath $outbox -PathType Leaf) { $secretFiles.Add('backend\var\dev-outbox.log') }
}
if ($secretFiles.Count -eq 0) { throw 'No secret files were found to export.' }

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$archive = Join-Path $destination "control-tower-secrets-$stamp.7z"
$partialArchive = "$archive.partial"
if (Test-Path -LiteralPath $archive) { throw "Secret archive already exists: $archive" }
if (Test-Path -LiteralPath $partialArchive) { throw "Partial secret archive already exists: $partialArchive" }
[string[]]$secretArguments = @($secretFiles)

Write-Host '7-Zip will now prompt for a recovery passphrase.'
Write-Host 'Save that passphrase in a password manager; it is not stored in the archive or repository.'
Push-Location $repoRoot
try {
    # -p without a value prompts securely; -mhe encrypts filenames as well as contents.
    & $sevenZip a -t7z -mx=9 -mhe=on -p $partialArchive @secretArguments
    if ($LASTEXITCODE -ne 0) { throw 'Encrypted secret archive creation failed.' }
}
finally {
    Pop-Location
}

Move-Item -LiteralPath $partialArchive -Destination $archive

$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$checksum = "$archive.sha256"
[System.IO.File]::WriteAllText($checksum, "$hash  $([System.IO.Path]::GetFileName($archive))" + [Environment]::NewLine)
Write-Host "Encrypted secret archive created: $archive"
Write-Host "Checksum: $checksum"
Write-Host 'Test the passphrase with: 7z t -p <archive>'
