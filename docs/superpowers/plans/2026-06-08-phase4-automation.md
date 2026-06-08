# Phase 4 — Automation (Scheduled Daily Briefing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily briefing run hands-off — a Windows scheduled task runs it at 7:00 AM on weekdays and emails the result, with per-run logs and a clean uninstall.

**Architecture:** Three small PowerShell scripts in a new `scripts/` directory — a runner the task calls (runs `python -m src.main`, logs output, propagates the exit code), a one-time setup script that registers the task via `Register-ScheduledTask` (with a `-WhatIf` dry-run), and a remove script. No Python changes; email uses the existing `main.py` path, configured via `.env`.

**Tech Stack:** PowerShell 7 (`pwsh`), Windows Task Scheduler (`ScheduledTasks` module), the existing Python venv at `.venv`. Run from the repo root `C:\VS Code\Stock Advisor`.

---

## File Structure

- **Create:** `scripts/run-briefing.ps1` — runner invoked by the scheduled task; runs the briefing, tees output to a dated log, exits with Python's code.
- **Create:** `scripts/setup-schedule.ps1` — one-time task registration; idempotent; supports `-WhatIf`; warns if wake timers are off.
- **Create:** `scripts/remove-schedule.ps1` — unregisters the task.
- **Modify:** `README.md` — add an "Automation (Phase 4)" section: Gmail App Password steps + rollout commands.

No test files: this is OS-integration glue (PowerShell + Task Scheduler + a user-set secret) and is verified by real runs, not unit tests. The Python suite (90 tests) is re-run unchanged to confirm no regression.

Conventions: scripts resolve the repo root from `$PSScriptRoot\..` so they are location-independent. Task name is **`StockAdvisorDailyBriefing`** everywhere.

---

### Task 1: Runner script (`scripts/run-briefing.ps1`)

**Files:**
- Create: `scripts/run-briefing.ps1`

- [ ] **Step 1: Create the script**

Create `scripts/run-briefing.ps1` with exactly this content:

```powershell
# Runs the Stock Advisor daily briefing and logs all output.
# Invoked by the scheduled task 'StockAdvisorDailyBriefing'. Safe to run by hand.
$ErrorActionPreference = "Continue"

$root   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("briefing-{0:yyyy-MM-dd}.log" -f (Get-Date))

"==== briefing run: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" |
    Tee-Object -FilePath $logFile -Append

if (-not (Test-Path $python)) {
    "ERROR: venv python not found at $python" | Tee-Object -FilePath $logFile -Append
    exit 1
}

Push-Location $root
try {
    & $python -m src.main 2>&1 | Tee-Object -FilePath $logFile -Append
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

"==== exit code: $code ====" | Tee-Object -FilePath $logFile -Append
exit $code
```

- [ ] **Step 2: Syntax-check the script (does not execute it)**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"
$errs = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path scripts\run-briefing.ps1).Path, [ref]$null, [ref]$errs) | Out-Null
if ($errs) { $errs | ForEach-Object { $_.Message }; "PARSE FAILED" } else { "PARSE OK" }
```

Expected: `PARSE OK`

- [ ] **Step 3: Verify the venv path it targets actually exists**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"; Test-Path ".venv\Scripts\python.exe"
```

Expected: `True` (confirms the runner will find Python). Do **not** execute the runner yet — that triggers a real, paid briefing run and is done in Task 5 once email is configured.

- [ ] **Step 4: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add scripts/run-briefing.ps1
git commit -m "feat(automation): runner script for the scheduled daily briefing"
```

---

### Task 2: Setup script (`scripts/setup-schedule.ps1`)

**Files:**
- Create: `scripts/setup-schedule.ps1`

- [ ] **Step 1: Create the script**

Create `scripts/setup-schedule.ps1` with exactly this content:

```powershell
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
```

- [ ] **Step 2: Syntax-check the script (does not execute it)**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"
$errs = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path scripts\setup-schedule.ps1).Path, [ref]$null, [ref]$errs) | Out-Null
if ($errs) { $errs | ForEach-Object { $_.Message }; "PARSE FAILED" } else { "PARSE OK" }
```

Expected: `PARSE OK`

- [ ] **Step 3: Dry-run with -WhatIf (previews, registers nothing)**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"; .\scripts\setup-schedule.ps1 -WhatIf
```

Expected: one or more `What if:` lines naming the target `StockAdvisorDailyBriefing` and the "Register task (Mon-Fri 7:00 AM)" operation. No task is actually created (confirm with `Get-ScheduledTask -TaskName StockAdvisorDailyBriefing -ErrorAction SilentlyContinue` → returns nothing).

- [ ] **Step 4: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add scripts/setup-schedule.ps1
git commit -m "feat(automation): idempotent setup script to register the scheduled task"
```

---

### Task 3: Remove script (`scripts/remove-schedule.ps1`)

**Files:**
- Create: `scripts/remove-schedule.ps1`

- [ ] **Step 1: Create the script**

Create `scripts/remove-schedule.ps1` with exactly this content:

```powershell
# Removes the 'StockAdvisorDailyBriefing' scheduled task. Safe if it doesn't exist.
$ErrorActionPreference = "Stop"
$taskName = "StockAdvisorDailyBriefing"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task '$taskName'."
} else {
    Write-Host "No scheduled task named '$taskName' found - nothing to remove."
}
```

- [ ] **Step 2: Syntax-check the script (does not execute it)**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"
$errs = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path scripts\remove-schedule.ps1).Path, [ref]$null, [ref]$errs) | Out-Null
if ($errs) { $errs | ForEach-Object { $_.Message }; "PARSE FAILED" } else { "PARSE OK" }
```

Expected: `PARSE OK`

- [ ] **Step 3: Verify it is safe to run when no task exists**

Run:

```powershell
Set-Location "C:\VS Code\Stock Advisor"; .\scripts\remove-schedule.ps1
```

Expected: `No scheduled task named 'StockAdvisorDailyBriefing' found - nothing to remove.` (No task exists yet, so this proves the no-op path is clean.)

- [ ] **Step 4: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add scripts/remove-schedule.ps1
git commit -m "feat(automation): remove script to unregister the scheduled task"
```

---

### Task 4: Document automation in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append an Automation section**

Add this section to the end of `README.md` (keep the existing content above it):

```markdown
## Automation (Phase 4) — hands-off daily briefing

Run the briefing automatically every weekday at 7:00 AM and email it to yourself.

### 1. Set up email (one time)

The briefing emails itself whenever `EMAIL_*` are set in `.env`.

1. Turn on 2-Step Verification for your Google account.
2. Create a Gmail **App Password**: Google Account -> Security -> 2-Step
   Verification -> App passwords. Name it "Stock Advisor". Copy the 16-character
   password.
3. In `.env`, set:
   - `EMAIL_USER` = your Gmail address
   - `EMAIL_PASSWORD` = the 16-character App Password (not your normal password)
   - `EMAIL_TO` = where to send it (your own address is fine)
   (`EMAIL_HOST`/`EMAIL_PORT` already default to Gmail's SSL settings.)

> To send to more than one person later, make `EMAIL_TO` a comma-separated list.
> (Private Bcc sharing is a small future addition.)

### 2. Verify email by hand BEFORE scheduling

```powershell
& .\.venv\Scripts\python.exe -m src.main
```

Confirm the briefing lands in your inbox. Only continue once it does.

### 3. Schedule it

Preview first, then register:

```powershell
.\scripts\setup-schedule.ps1 -WhatIf    # preview — creates nothing
.\scripts\setup-schedule.ps1            # actually register the task
```

If it warns that wake timers are off, follow the printed `powercfg` fix (or ignore
it — the task still runs the next time you turn the PC on).

### 4. Test the task without waiting for 7:00 AM

```powershell
Start-ScheduledTask -TaskName StockAdvisorDailyBriefing
Get-Content (".\logs\briefing-{0:yyyy-MM-dd}.log" -f (Get-Date)) -Tail 20
```

You should see the run logged and the email arrive.

### Manage it

```powershell
Get-ScheduledTask     -TaskName StockAdvisorDailyBriefing   # see it / its state
Get-ScheduledTaskInfo -TaskName StockAdvisorDailyBriefing   # last run time + result
.\scripts\remove-schedule.ps1                               # stop automation
```
```

- [ ] **Step 2: Commit**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
git add README.md
git commit -m "docs: document Phase 4 automation setup and rollout"
```

---

### Task 5: Rollout & end-to-end verification (user-guided)

This task involves the user's Gmail secret and a real (paid) briefing run, so it is
done interactively with the user — not committed (all artifacts are git-ignored).

- [ ] **Step 1: Confirm Python suite still green (no regression)**

```powershell
Set-Location "C:\VS Code\Stock Advisor"; & ".\.venv\Scripts\python.exe" -m pytest -q
```

Expected: `90 passed`.

- [ ] **Step 2: User configures `.env` email**

Walk the user through README section 1 (Gmail App Password + `EMAIL_USER`/
`EMAIL_PASSWORD`/`EMAIL_TO`). The user does this; do not ask for the password.

- [ ] **Step 3: Manual email verification**

```powershell
Set-Location "C:\VS Code\Stock Advisor"; & ".\.venv\Scripts\python.exe" -m src.main
```

Expected: report prints, `[briefing emailed]` appears, and the user confirms the
email arrived. If `[email failed: ...]` shows instead, fix `.env` before proceeding.

- [ ] **Step 4: Register the task**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
.\scripts\setup-schedule.ps1 -WhatIf
.\scripts\setup-schedule.ps1
```

Expected: dry-run shows the `What if:` preview; the real run prints
`Registered 'StockAdvisorDailyBriefing' ...`. Address any wake-timer warning.

- [ ] **Step 5: On-demand task run + log/inbox check**

```powershell
Set-Location "C:\VS Code\Stock Advisor"
Start-ScheduledTask -TaskName StockAdvisorDailyBriefing
Start-Sleep -Seconds 90
Get-ScheduledTaskInfo -TaskName StockAdvisorDailyBriefing | Select-Object LastRunTime, LastTaskResult
Get-Content (".\logs\briefing-{0:yyyy-MM-dd}.log" -f (Get-Date)) -Tail 20
```

Expected: `LastTaskResult` is `0`; the log shows the run with `exit code: 0`; the
user confirms the email arrived. This proves the full scheduled path works without
waiting for 7:00 AM.

---

## Notes for the implementer

- **Why no unit tests:** Tasks 1-4 produce PowerShell/Task-Scheduler glue and a doc;
  there is nothing meaningfully unit-testable, and faking Task Scheduler would test
  the fake, not the system. Real verification is the parser checks, the `-WhatIf`
  dry-run, and the on-demand task run in Task 5. The Python code is untouched.
- **`$LASTEXITCODE` through the pipe:** in `& $python ... 2>&1 | Tee-Object`, the
  native process still sets `$LASTEXITCODE` (Tee-Object is a cmdlet and doesn't reset
  it), so the runner propagates Python's real exit code.
- **Logged-on principal:** `-LogonType Interactive` runs as the user with no stored
  password; combined with `-WakeToRun` it runs after a wake-from-sleep, and
  `-StartWhenAvailable` covers a cold boot.
- **Idempotency:** re-running `setup-schedule.ps1` unregisters then re-registers, so
  it's safe to run again after changing settings.
```
