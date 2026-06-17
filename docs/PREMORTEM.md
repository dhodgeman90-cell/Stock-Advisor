# Stock Advisor — Premortem (handoff readiness)

**Frame:** It's three months from now. You sent the app to a non-technical friend/family member
to run on their own Windows machine, and it went badly. What went wrong? This is a fresh-eyes
review of the *distribution* risk surface — not the algorithm. The app itself is feature-complete
(rules-only by default, AI/email opt-in, 279 tests). The risks below are almost all about the gap
between "works on the developer's machine" and "works in a stranger's hands."

Each item: the failure → why it bites *this* user → cheapest mitigation. Ranked by likelihood ×
impact within each bucket.

---

## Fix before sending (candidates — your call)

### 1. The packaged `.exe` has never been tested end-to-end
- **Failure:** PyInstaller/Inno builds exist, but no test installs the actual `.exe` on a clean
  machine and confirms it launches, opens the browser, and shows the UI. A frozen-app-only bug
  (missing hidden import, a data file not bundled, a path that only resolves in dev) ships silently.
- **Why it bites:** This is the *first thing* the recipient does. If it fails here, the whole
  handoff fails on contact, and a non-technical user can't diagnose a frozen-exe traceback.
- **Mitigation:** One manual pass on a clean Windows VM (or a fresh user account) before sending —
  see the checklist at the bottom. This is the single highest-value action.
- **Likelihood:** Low–Med · **Impact:** Critical (total failure on first run).

### 2. Browser auto-open can fail with only a console-window hint
- **Failure:** [app.py:43](../src/app.py#L43) — `threading.Timer(1.0, lambda: webbrowser.open(url)).start()`.
  If the default-browser handler is odd/missing, nothing opens. The app *is* running, but the user
  sees only a console window.
- **Mitigating fact:** [app.py:41](../src/app.py#L41) prints `Stock Advisor running at <url>` to that
  console first — so it's not *totally* silent, but a non-technical user won't think to read a black
  terminal window or copy a URL out of it.
- **Mitigation:** Make the console line impossible to miss (e.g. "👉 If your browser didn't open,
  go to http://127.0.0.1:8765"), and/or say it in the README's first-run steps.
- **Likelihood:** Med · **Impact:** High (user concludes "it's broken").

### 3. Email setup fails silently for someone who doesn't know "app passwords"
- **Failure:** Enabling email requires a Gmail *app password* (needs 2FA enabled on the Google
  account). Paste a normal password and it just fails. There's a "Send test" button, but nothing
  walks the user through Google's flow, and a scheduled-run send failure only prints
  `[email failed: ...]` ([main.py:357](../src/main.py#L357)) to a log they'll never open.
- **Why it bites:** Email is the marquee "it just shows up every morning" feature. If they can't
  get it working and get no useful error, they quietly give up on it.
- **Mitigation:** Short in-UI note + README link on creating a Gmail app password; surface the
  test-send result clearly. (Lower-effort alternative: tell them up front email is "advanced,
  optional" so failure isn't a surprise.)
- **Likelihood:** High · **Impact:** Med.

---

## Fix later (real, but survivable for a first recipient)

### 4. Data-source failures degrade silently with no "unavailable today" signal
- **Failure:** yfinance / congress / WSB / news feeds all fall back gracefully (cache or empty), but
  the briefing gives no visible "couldn't load X today" indicator. A holdings price that fails to
  fetch renders as "price unavailable" with no explanation of scope.
- **Why it bites:** On a flaky home connection the user can't tell "the app is fine, the internet
  hiccuped" from "the app is broken." Erodes trust over weeks.
- **Mitigation:** A small status line in the briefing ("Congress data: stale, last updated …").
- **Likelihood:** Med · **Impact:** Low–Med.

### 5. Scheduled-task / email errors land in a log file nobody reads
- **Failure:** The 7 AM task writes failures to `logs/briefing-<date>.log`. If a run fails, the user
  just sees *no email* and no explanation.
- **Mitigation:** On failure, still send (or surface in the UI on next open) a one-line "yesterday's
  run failed" notice. Defer unless they rely on the scheduled run.
- **Likelihood:** Med · **Impact:** Low–Med.

### 6. README may invite broker sync that the beta deliberately doesn't ship
- **Failure:** The design docs are explicit that **broker sync is NOT in the beta**
  ([distribution-design spec §55](superpowers/specs/2026-06-15-stock-advisor-distribution-design.md),
  [packaging plan](superpowers/plans/2026-06-17-stock-advisor-packaging.md)). If the *user-facing*
  README still mentions `python -m src.link_broker` / SnapTrade, the recipient may try it and fail.
- **Mitigation:** Confirm the README handed to the recipient doesn't reference broker sync (or marks
  it clearly "owner-only, not in this build"). Pure doc edit.
- **Likelihood:** Med · **Impact:** Low (confusion, not breakage).

---

## Accept & document (inherent trade-offs — flag, don't fix)

### 7. SmartScreen "Windows protected your PC" on the unsigned installer
- Already documented in [RELEASE.md](RELEASE.md) (unsigned; tester clicks **More info → Run anyway**).
  Real friction — novices read "protected your PC" as *malware* and stop. The only true fix is a
  code-signing certificate ($$/yr). For friends & family, a heads-up text/screenshot ("Windows will
  warn you it's unrecognized — that's expected, click More info → Run anyway") is enough.

### 8. 7 AM wake is unreliable on a laptop on battery
- Documented in [setup-schedule.ps1](../scripts/setup-schedule.ps1): this is a Modern-Standby machine
  class issue, not a bug. Tell the recipient: plug in overnight, or just open the app and click Run.

### 9. Disclaimer strength vs. AI-generated rotation suggestions
- The one-time disclaimer ([ui/index.html](../ui/index.html)) says "information, not financial advice."
  But the briefing prints a concrete "Today's rotation: add X (high conviction)," and with AI enabled
  the risk agent can emit a "veto." A naive user could read that as advice. Not a code bug — a
  judgment call on wording/liability. **Flagging for your decision**, not recommending a code change
  here. If real money beyond friends & family is ever in scope, get the disclaimer wording reviewed.

---

## Checked — NOT a risk

- **Congress cache writing to Program Files (permission denied):** investigated and **false for the
  shipped path.** Production passes the per-user path —
  [main.py:217](../src/main.py#L217) `cache_path=profile.data_dir / "congress_trades.json"` → `%APPDATA%\StockAdvisor\data`.
  The `ROOT/data` default in [congress.py:18](../src/congress.py#L18) is only hit by tests/scripts,
  never by the packaged app. No action needed.
- **Secrets in the shipped build:** none. Secrets live in the OS keyring (per-user), and the build
  hygiene gate blocks `.env`/hardcoded paths. Good.

---

## Pre-send test checklist (do this on a clean Windows account/VM)

- [ ] Install `StockAdvisor-Setup-<version>.exe`; click through the SmartScreen warning as a first-timer would.
- [ ] Launch → confirm the browser opens to the dashboard (and that the console URL is findable if it doesn't).
- [ ] Confirm the disclaimer modal appears and gates the first briefing.
- [ ] Click **Run** with no secrets configured → confirm a rules-only briefing renders.
- [ ] Integrations: add an Anthropic key → run → confirm AI sections appear (and that a *bad* key fails legibly).
- [ ] Integrations: set up Gmail app password → **Send test** → confirm it arrives (and a bad password fails legibly).
- [ ] Disconnect the network → Run → confirm it degrades to "unavailable" rather than crashing.
- [ ] (If scheduling) run `setup-schedule.ps1` in an **elevated** shell; confirm the task is registered.
