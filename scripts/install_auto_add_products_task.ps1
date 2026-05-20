param(
    [string]$TaskName = "SmartSaver-AutoAddProducts",
    [string]$StartTime = "02:00",
    [ValidateSet("Daily", "Weekly")]
    [string]$Schedule = "Daily",
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$DayOfWeek = "Sunday"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $projectRoot "scripts\run_auto_add_products.ps1"

if (-not (Test-Path $runner)) {
    throw "Runner script not found: $runner"
}

try {
    $atTime = [DateTime]::ParseExact($StartTime, "HH:mm", $null)
} catch {
    throw "Invalid StartTime '$StartTime'. Use HH:mm format, e.g. 02:00"
}

$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
if ($Schedule -eq "Weekly") {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $atTime
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $atTime
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

$userId = if ($env:USERDOMAIN) {
    "$($env:USERDOMAIN)\$($env:USERNAME)"
} else {
    $env:USERNAME
}

$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

if ($Schedule -eq "Weekly") {
    Write-Host "Registering weekly task '$TaskName' on $DayOfWeek at $StartTime for user '$userId' ..."
} else {
    Write-Host "Registering daily task '$TaskName' at $StartTime for user '$userId' ..."
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Done. Task created/updated: $TaskName"
Write-Host "You can inspect it with: Get-ScheduledTask -TaskName $TaskName | Format-List *"
