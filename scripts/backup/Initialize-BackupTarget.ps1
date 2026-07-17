[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [switch]$AllowInsideRepository
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$destinationFull = [System.IO.Path]::GetFullPath($DestinationRoot)
$repoPrefix = $repoRoot.TrimEnd('\') + '\'

if (-not $AllowInsideRepository -and
    ($destinationFull -eq $repoRoot -or $destinationFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw 'The backup target must be outside the repository. Use -AllowInsideRepository only for a disposable verification target.'
}

if (-not (Test-Path -LiteralPath $destinationFull)) {
    if ($PSCmdlet.ShouldProcess($destinationFull, 'Create backup target directory')) {
        [System.IO.Directory]::CreateDirectory($destinationFull) | Out-Null
    }
    else {
        return
    }
}

$destinationResolved = (Resolve-Path -LiteralPath $destinationFull).Path
$marker = Join-Path $destinationResolved '.act-backup-target'

if (Test-Path -LiteralPath $marker) {
    $existing = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($existing.project -ne 'ai-agent-control-tower' -or $existing.schemaVersion -ne 1) {
        throw "Destination marker belongs to another project: $($existing.project)"
    }
    Write-Host "Backup target is already initialized: $destinationResolved"
    return
}

$payload = [ordered]@{
    schemaVersion = 1
    project       = 'ai-agent-control-tower'
    initializedAt = [DateTime]::UtcNow.ToString('o')
    repository    = 'https://github.com/Umair-zaka-ui/ai-agent-control-tower.git'
}

if ($PSCmdlet.ShouldProcess($marker, 'Create project safety marker')) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($marker, ($payload | ConvertTo-Json), $utf8)
}

Write-Host "Initialized safe backup target: $destinationResolved"
Write-Host 'Keep this marker in place; backup and retention operations refuse unmarked destinations.'
