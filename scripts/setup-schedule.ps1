# Registers the 'StockAdvisorDailyBriefing' scheduled task (Mon-Fri 7:00 AM) and
# makes sure the power plan lets the PC wake to run it.
#
# Runs the task as SYSTEM (whether or not you are logged on) so it isn't deferred
# while the laptop is in connected standby. Registering a SYSTEM task and changing
# power settings BOTH require elevation, so run this in an ELEVATED PowerShell:
#   Right-click PowerShell -> "Run as administrator", then:  .\scripts\setup-schedule.ps1
# Preview first (no admin needed) with:  .\scripts\setup-schedule.ps1 -WhatIf
#
# NOTE: this machine only supports Modern Standby (S0) -- there is no classic sleep.
# On BATTERY, Modern Standby suppresses the wake timer, so the morning run is only
# reliable when the laptop is PLUGGED IN. Either way the task catches up (via
# StartWhenAvailable) the next time the PC is awake.
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"
$taskName = "StockAdvisorDailyBriefing"
$root     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner   = Join-Path $root "scripts\run-briefing.ps1"

# Elevation is required to register a SYSTEM task and to change power settings.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $WhatIfPreference) {
    Write-Warning "This must run in an ELEVATED PowerShell (Run as administrator)."
    Write-Host    "  Close this window, right-click PowerShell -> 'Run as administrator', then re-run."
    return
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 7:00AM

$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# SYSTEM / ServiceAccount: runs whether or not you are logged on, in session 0,
# so connected-standby throttling of the interactive desktop does not defer it.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" `
    -LogonType ServiceAccount -RunLevel Highest

# Idempotent: drop an existing task of the same name first so re-running updates it.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    if ($PSCmdlet.ShouldProcess($taskName, "Unregister existing task")) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}

if ($PSCmdlet.ShouldProcess($taskName, "Register SYSTEM task (Mon-Fri 7:00 AM)")) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "Stock Advisor: emails the daily morning briefing on weekdays at 7:00 AM (runs as SYSTEM)." | Out-Null
    Write-Host "Registered '$taskName' as SYSTEM (Mon-Fri 7:00 AM). Runs: $runner"
}

# Make sure the power plan honors wake timers and won't hibernate on AC. These are
# idempotent (setting a value that is already set is a no-op).
$sleepSub = "238C9FA8-0AAD-41ED-83F4-97BE242C8F20"   # Sleep subgroup
$wakeGuid = "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D"   # Allow wake timers (0=off 1=on 2=important-only)
$hibGuid  = "9D7815A6-7EE4-497E-8888-515A05F02364"   # Hibernate after (0 = never)
if ($PSCmdlet.ShouldProcess("active power plan", "Enable wake timers (AC+DC); never hibernate on AC")) {
    powercfg /SETACVALUEINDEX SCHEME_CURRENT $sleepSub $wakeGuid 1
    powercfg /SETDCVALUEINDEX SCHEME_CURRENT $sleepSub $wakeGuid 1
    powercfg /SETACVALUEINDEX SCHEME_CURRENT $sleepSub $hibGuid  0
    powercfg /SETACTIVE SCHEME_CURRENT
    Write-Host "Power plan: wake timers ENABLED (AC+DC); AC hibernate set to Never."
}

Write-Host ""
Write-Host "IMPORTANT: keep the laptop PLUGGED IN overnight. This machine is Modern"
Write-Host "Standby only (no classic sleep); on battery the 7:00 AM wake is unreliable."
Write-Host "To verify the SYSTEM task works now, run (in this elevated window):"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$taskName' | Select LastRunTime, LastTaskResult"
Write-Host "  # LastTaskResult 0 + a fresh email = success."
