[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot,

    [string]$TaskName = 'AI Agent Control Tower Backup',
    [string]$DailyAt = '02:00',
    [switch]$Replace,
    [switch]$EnablePruning,
    [int]$KeepCompletedSnapshots = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$destination = (Resolve-Path -LiteralPath $DestinationRoot).Path
$marker = Join-Path $destination '.act-backup-target'
if (-not (Test-Path -LiteralPath $marker)) { throw 'Destination is not an initialized Control Tower backup target.' }
$markerData = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($markerData.project -ne 'ai-agent-control-tower' -or $markerData.schemaVersion -ne 1) {
    throw 'Backup marker is invalid or belongs to another project.'
}

$parsedTime = [DateTime]::MinValue
if (-not [DateTime]::TryParseExact($DailyAt, 'HH:mm', $null, [Globalization.DateTimeStyles]::None, [ref]$parsedTime)) {
    throw 'DailyAt must use 24-hour HH:mm format, for example 02:00.'
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Replace) { throw "Scheduled task already exists: $TaskName. Use -Replace to update it." }

$backupScript = (Resolve-Path (Join-Path $PSScriptRoot 'Backup-ControlTower.ps1')).Path
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$backupScript`" -DestinationRoot `"$destination`""
if ($EnablePruning) {
    $arguments += " -Prune -KeepCompletedSnapshots $KeepCompletedSnapshots"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory (Split-Path -Parent $backupScript)
$trigger = New-ScheduledTaskTrigger -Daily -At $parsedTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$userId = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Verified Git + PostgreSQL recovery snapshot for AI Agent Control Tower.'

if ($PSCmdlet.ShouldProcess($TaskName, "Register daily backup task at $DailyAt")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force:$Replace | Out-Null
}

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Destination: $destination"
Write-Host "Daily time: $DailyAt (runs while this user is logged in; missed runs start when available)"
Write-Host 'Run it once manually and verify the resulting snapshot before relying on the schedule.'
