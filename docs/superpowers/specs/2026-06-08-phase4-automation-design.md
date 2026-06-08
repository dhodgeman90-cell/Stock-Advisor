# Phase 4 — Automation (Daily Scheduled Briefing) — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)
**Area:** `scripts/` (new PowerShell glue), `.env` (user config), `docs`/`README`

## Problem

The daily briefing (`python -m src.main`) currently has to be run by hand. Phase 4
makes it hands-off: every weekday morning the briefing runs automatically and the
result is emailed to the user, so they can read it before the US market opens
without touching the computer.

## Goal

A reliable, reproducible Windows Task Scheduler setup that runs the briefing at
**7:00 AM on weekdays** and **emails it** to the user, with per-run logs for
debugging and a clean way to remove the schedule later.

Non-goals (YAGNI this phase): Cc/Bcc email support (deferred — see "Email sharing"
below), log rotation, waking a fully powered-off PC, any change to the scoring or
briefing logic.

## Decisions (from brainstorming)

1. **Delivery: email.** The briefing is emailed to the user's inbox each morning
   (the original product vision). `main.py` already emails when `EMAIL_*` are set in
   `.env`; no code change needed — only configuration.
2. **Time: 7:00 AM, weekdays only.** Markets are closed weekends, so no run (saves
   API spend). The briefing uses the prior day's close, so a pre-open run gives a
   full plan for the day.
3. **If the PC is asleep/off at 7:00: wake it, with a catch-up fallback.**
   `-WakeToRun` wakes a sleeping PC to run on time; `-StartWhenAvailable` runs the
   briefing as soon as possible after boot if it was fully off and missed 7:00. The
   two together cover both states.
4. **Task creation: a committed PowerShell setup script** (`Register-ScheduledTask`),
   run once by the user with a `-WhatIf` dry-run preview first. Reproducible,
   version-controlled, re-runnable — not a one-off GUI click-through.

## Components

All new files live in a new `scripts/` directory. No Python changes.

### 1. `scripts/run-briefing.ps1` — the runner the task calls

- Resolves the repo root from its own location (`$PSScriptRoot\..`) so it works no
  matter the caller's working directory.
- Runs `& "<repo>\.venv\Scripts\python.exe" -m src.main` from the repo root.
- Writes a timestamped start banner, then tees **stdout + stderr** to
  `logs\briefing-<yyyy-MM-dd>.log` (append).
- Exits with Python's exit code (`exit $LASTEXITCODE`) so Task Scheduler's
  "Last Run Result" is meaningful (`0x0` = success). A pre-briefing crash leaves its
  traceback in the log.

### 2. `scripts/setup-schedule.ps1` — run once by the user

- Registers a task named **`StockAdvisorDailyBriefing`** via `Register-ScheduledTask`.
- **Trigger:** `New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7:00AM`.
- **Action:** `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\run-briefing.ps1"`.
- **Settings:** `New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`.
- **Principal:** current user, run only when logged on (no stored password). After a
  wake-from-sleep the session is still logged on, so this is sufficient.
- **Idempotent:** if a task of the same name exists, unregister it first, so
  re-running cleanly updates settings.
- **Power-setting check:** after registering, query whether "Allow wake timers" is
  enabled in the active power plan; if not, print a clear warning plus the one-line
  `powercfg` fix. The script does not silently assume wake will work.
- Supports `-WhatIf` so the user can preview what will be created before doing it.

### 3. `scripts/remove-schedule.ps1` — clean uninstall

- `Unregister-ScheduledTask -TaskName StockAdvisorDailyBriefing -Confirm:$false`,
  guarded so it reports cleanly if the task isn't present.

### 4. Email configuration (user step, no code)

- User fills `EMAIL_USER` / `EMAIL_PASSWORD` / `EMAIL_TO` in `.env` with a Gmail
  **App Password** (`EMAIL_HOST`/`EMAIL_PORT` already default correctly in code).
- `main.py` emails the briefing whenever all three are set (existing behavior,
  [src/main.py:156](../../src/main.py)).

## Logging & error handling

- Per-run log: `logs\briefing-<yyyy-MM-dd>.log` (stdout + stderr, timestamped banner).
- `logs/` is **already** in `.gitignore` (whole directory) — no change needed; logs
  stay local like `reports/`.
- Exit code propagated from Python so failures are visible in Task Scheduler.
- Existing graceful degradation in `main.py` (data cache fallback; email wrapped in
  try/except printing `[email failed: …]`) now lands in the log instead of a
  vanished console, so a broken email is discoverable.

## Rollout order (de-risks email before automating)

1. Create the Gmail App Password; fill `.env`.
2. **Verify email by hand:** run `python -m src.main` once; confirm the briefing
   arrives in the inbox. Only proceed if it does.
3. `scripts\setup-schedule.ps1 -WhatIf` to preview, then run it for real.
4. **Verify the task on-demand:** `Start-ScheduledTask -TaskName StockAdvisorDailyBriefing`;
   confirm `logs\briefing-<today>.log` is written and the email arrives — without
   waiting for 7:00 AM.

## Testing

Phase 4 is infrastructure (PowerShell + Task Scheduler + a user-set secret), which
is not meaningfully unit-testable; no fake tests will be manufactured. Verification
is the real-run checklist above (manual email send → on-demand task run → log +
inbox confirmed). The Python side is unchanged and remains covered by the existing
90-test suite, which is re-run to confirm no regression.

## Email sharing (future, deferred)

Sharing the briefing with others is intentionally out of scope now. Two clean paths
when needed:
- **Quick:** `EMAIL_TO` already accepts comma-separated addresses (all visible in the
  To line) — no code change.
- **Proper:** add `EMAIL_CC` / `EMAIL_BCC` env vars and set the matching headers in
  `briefing.send_email` (Bcc preferred for a recipient list, to keep addresses
  private). ~10 lines plus a unit test, well-isolated. Not built this phase.

## Out of scope

Cc/Bcc support, log rotation, waking a fully-off PC, running when not logged on
(stored credentials), and any change to scoring/exit/briefing logic.
