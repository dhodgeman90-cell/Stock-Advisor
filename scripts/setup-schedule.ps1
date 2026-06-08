# Registers the 'StockAdvisorDailyBriefing' scheduled task (Mon-Fri 7:00 AM).
# Run ONCE. Preview first with:  .\scripts\setup-schedule.ps1 -WhatIf
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"
$taskName = "StockAdvisorDailyBriefing"
$root     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner   = Join-Path $root "scripts\run-briefing.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 7:00AM

$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

# Idempotent: drop an existing task of the same name first so re-running updates it.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    if ($PSCmdlet.ShouldProcess($taskName, "Unregister existing task")) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}

if ($PSCmdlet.ShouldProcess($taskName, "Register task (Mon-Fri 7:00 AM)")) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "Stock Advisor: emails the daily morning briefing on weekdays at 7:00 AM." | Out-Null
    Write-Host "Registered '$taskName' (Mon-Fri 7:00 AM). Runs: $runner"
}

# Read-only check: warn if 'Allow wake timers' is disabled in the active power plan.
if (-not $WhatIfPreference) {
    $sleepSub = "238C9FA8-0AAD-41ED-83F4-97BE242C8F20"
    $wakeGuid = "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D"
    $out = (powercfg /QUERY SCHEME_CURRENT $sleepSub $wakeGuid 2>$null | Out-String)
    $m = [regex]::Match($out, "Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)")
    if ($m.Success -and ([Convert]::ToInt32($m.Groups[1].Value, 16) -eq 0)) {
        Write-Warning "Wake timers are OFF in your active power plan; the PC may not wake at 7:00 AM."
        Write-Host    "  Enable (run PowerShell as Administrator):"
        Write-Host    "    powercfg /SETACVALUEINDEX SCHEME_CURRENT $sleepSub $wakeGuid 1"
        Write-Host    "    powercfg /SETACTIVE SCHEME_CURRENT"
        Write-Host    "  Either way, the task still catches up the next time you turn the PC on."
    }
}
