# Removes the 'StockAdvisorDailyBriefing' scheduled task. Safe if it doesn't exist.
$ErrorActionPreference = "Stop"
$taskName = "StockAdvisorDailyBriefing"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task '$taskName'."
} else {
    Write-Host "No scheduled task named '$taskName' found - nothing to remove."
}
