# Stock Advisor — Distribution & Packaging Design Spec

**Date:** 2026-06-15
**Status:** Design approved; pending spec review → implementation plan
**Owner skill level:** Beginner — every command must be explained before running
**Builds on:** `2026-06-08-stock-advisor-design.md` (the engine this packages)

---

## 1. Overview

Stock Advisor is today a personal, local Python CLI: it runs a daily pipeline
(fetch market data → deterministic scoring → optional AI agents → adjudicate →
briefing) for one person — the owner — on one machine. Code, keys, paths, and the
owner's real financial data are intentionally tangled together because there is
only one user.

This spec covers **how to deliver that tool to other people as a standalone app**,
without compromising sensitive data on either end. The work is fundamentally a
**data-isolation + distribution** problem, not a rewrite of the engine.

### Two horizons (explicit, agreed)

- **Now — friends & family beta.** A standalone Windows desktop app, **rules-only
  by default** (no AI, no keys, no cost), where each person's data lives entirely
  on their own machine. Must work for the *least technical* recipient.
- **Later — subscription product (only if it proves valuable).** A hosted service
  where the owner runs a server, holds the AI key, and offers a guided wizard for
  power features (broker sync, email). Design choices now must not block this.

### Success criteria

1. A beta tester can install and get a working briefing with **no secrets of any
   kind** and no terminal contact.
2. **No sensitive information is compromised on either end** (see Section 7).
3. The owner's personal copy (with SnapTrade broker sync) keeps working unchanged.
4. The layers built now (engine + API + UI) are the foundation the future hosted
   product reuses, not throwaway work.

### Honest framing

- This is a **multi-step build**, not an afternoon. Today there is no installer;
  the server layer, UI, profile-directory refactor, and packaging must be built.
- The architecture removes the major data risks *by construction*, but only if the
  build-hygiene rules in Section 7 are followed deliberately every time.

---

## 2. Decisions (locked during brainstorming)

| Question | Decision |
|---|---|
| Audience | Friends & family first; a sellable product later if it proves valuable. |
| Recipient skill | **Mixed** — must work for the least technical person (true double-click). |
| Holdings/positions | **Manual positions by default.** Optional broker sync stays a gated module for tinkerers. **Broker sync is NOT shipped in the beta.** Full guided BYO-broker wizard deferred to the product phase. |
| AI agents & cost | **Rules-only by default** (agents off, no key, no cost). Optional BYO Anthropic key for tinkerers. Future product = subscription where the owner runs the server and proxies the key. |
| Briefing delivery | In-app display + saved dated report by default. **Optional** BYO email (Gmail app password) via the Integrations page. |
| Packaging approach | **Approach A — local web UI** (engine + thin FastAPI server + browser dashboard), because the API/UI layer carries over to the future hosted product. |

### Why the rules-only-first + BYO model is the core of the safety story

Because the beta ships **rules-only with no proxy server**, the owner's secrets are
never inside the distributed app. There is no shared key, no SnapTrade partner
credential, no server holding anyone's data. You cannot leak what isn't there.
Every secret a *tinkerer* later opts into (AI, email) stays on their machine and
talks **directly** to the relevant service — never routed through the owner.

---

## 3. Architecture

Three clean layers. The bottom two are shared with the future hosted product; only
the top (local browser vs. cloud web) changes.

```
┌─────────────────────────────────────────────┐
│  UI layer  — browser dashboard (local)       │  ← swappable: desktop now, cloud later
├─────────────────────────────────────────────┤
│  Server   — thin FastAPI app (127.0.0.1)     │  ← same API the SaaS will expose
│   • GET /api/briefing/today  • settings CRUD │
│   • POST /api/run            • positions CRUD │
│   • PUT /api/secrets (write-only)            │
├─────────────────────────────────────────────┤
│  Engine   — existing pipeline, headless      │  ← unchanged logic, parameterized paths
│   data → scoring → exits → adjudicate → brief │
└─────────────────────────────────────────────┘
        ▲ reads/writes ▼
   Per-user PROFILE DIR (outside the app):
   %APPDATA%\StockAdvisor\  →  config/  data/  reports/  + OS credential store
```

**The decisive idea:** all of a person's data lives in a per-user **profile
directory** (`%APPDATA%\StockAdvisor\`), entirely separate from the installed
program files. The shipped app contains **zero** personal data. Each machine
generates its own profile on first run. This is what makes the app "standalone"
and isolates every user's data by construction.

---

## 4. Engine refactor (the decoupling)

Goal: the pipeline takes *"whose run is this?"* as an input instead of assuming the
owner. This is mostly plumbing — the engine already degrades gracefully without a
key (`has_llm` gate in `main.py`) and `config.py` loaders already accept a
`config_dir` argument.

- **Introduce a `Profile` object** carrying `config_dir`, `data_dir`,
  `reports_dir`, and a `secrets` source. Replace the module-level `ROOT`-derived
  paths in `main.py` by threading a `Profile` through `run()`.
- **Change secret lookup order** from "repo `.env`" to:
  **OS credential store → profile-dir `.env` → process environment.** The engine
  never assumes a secret exists.
- **`run()` returns a structured result** (ranked / vetoed / holdings / discovery /
  regime), in addition to writing the text + HTML report, so the server can render
  the dashboard and serve JSON without re-running the pipeline.
- **The owner's personal CLI keeps working.** A thin wrapper builds a `Profile`
  pointing at the existing repo `config/` and `.env` (and the SnapTrade broker
  path), so the owner's daily run is untouched. The beta build constructs a
  different `Profile` pointing at `%APPDATA%`.

---

## 5. The local web app (server + UI)

### Server (FastAPI)
- Bound to **127.0.0.1 only** — never network-exposed — on a local port.
- Endpoints:
  - `GET /api/briefing/today` — latest result (saved, or freshly run).
  - `POST /api/run` — trigger a pipeline run, report progress/status.
  - `GET/PUT /api/settings` — watchlist, weights, exit rules.
  - `GET/PUT /api/positions` — manual holdings.
  - `PUT /api/secrets` — **write-only**; writes to the OS credential store. Secrets
    are never read back out in plaintext (the UI shows only "set / not set").

### UI (browser dashboard)
Plain HTML/JS, no heavy framework (keeps the build small and the future cloud port
clean). Four screens:
1. **Briefing** — renders the existing `render_briefing_html` output.
2. **Watchlist** — add/remove tickers, edit settings (shortlist size, lookback).
3. **Positions** — manual holdings entry (ticker, entry price, optional date/shares).
4. **Integrations** — off by default; where a tinkerer enables AI (BYO Anthropic
   key) or email (BYO Gmail app password). Broker is absent in the beta build.

### Launcher
A small entry point starts the server and opens the user's **default browser** to
`127.0.0.1:<port>`. Most robust option for beta. A windowed "app feel" (e.g.
pywebview) is an easy later swap, not required now.

---

## 6. Onboarding (first run)

Deliberately minimal — no heavy wizard for the beta:

1. First launch detects no profile → creates `%APPDATA%\StockAdvisor\` and seeds it
   with **bundled default** `watchlist.yaml`, `weights.yaml`, `exits.yaml`,
   `adjudicator.yaml` (copies of sane defaults — none of the owner's personal files).
2. One welcome screen: **accept the disclaimer** ("information, not advice," stored
   so it shows once), confirm or edit the starter watchlist, done.
3. Integrations (AI/email) are an **optional settings page the user can ignore
   entirely** — not a gate. The full guided BYO-key wizard is deferred to the
   product phase.

---

## 7. Security & build hygiene (non-negotiable)

A named checklist enforced on every build:

- **Clean-tree build.** Build from a tree that explicitly **excludes** `.env`,
  `data/`, `reports/`, and the owner's personal `config/`. Nothing personal in the
  package. (This is the single real risk on the owner's side and it is fully under
  our control.)
- **Per-user profile dir.** App code and user data are never co-located; user data
  lives only in `%APPDATA%\StockAdvisor\`.
- **Secrets in the OS credential store**, never plaintext, never shipped.
- **Server bound to 127.0.0.1** only.
- **No broker sync in the beta build**; no shipped keys of any kind.
- **First-run disclaimer** acceptance (information, not advice) — shipping
  responsibly, not a data issue.

### Data-flow summary (why "no compromise on either end" holds)

- **Default mode:** only *public* market data is fetched; the user's watchlist and
  positions never leave their machine. There is nothing sensitive to compromise.
- **Opt-in AI/email:** the BYO secret stays on the user's machine and talks
  directly to Anthropic/Gmail — never through the owner.
- **Owner's side:** no secrets are in the distributed app, so none can leak from it.

---

## 8. Packaging & distribution

- **PyInstaller one-folder build** (one-folder, *not* one-file — meaningfully fewer
  antivirus false positives) bundling Python, dependencies, the FastAPI app, the
  static UI, and the default configs.
- **Inno Setup installer**: Start Menu + desktop shortcut, a proper uninstaller, and
  an **optional** "run the briefing every morning" checkbox that creates a Windows
  Task Scheduler job. Default behavior is simplest: the pipeline runs when the user
  opens the app.
- **Updates for beta are manual** — the owner sends "v0.2." Auto-update is
  product-phase.

### Known frictions (flagged honestly, not hidden)

- **Windows SmartScreen** warns on an unsigned installer ("Windows protected your
  PC"). Acceptable for friends & family *with a heads-up* (More info → Run anyway).
  A code-signing certificate (~$200–500/yr) removes it — worth it only at the
  product stage.
- **Market data (yfinance)** relies on Yahoo's undocumented endpoints and is
  occasionally flaky. Not a security issue; the engine already has a stale-cache
  fallback.

---

## 9. Scope: Beta MVP vs. later

**Beta MVP (must-have for a shippable hand-off):**
- Engine refactor — `Profile` object + per-user profile dir (Section 4).
- Thin FastAPI server + minimal UI: view Briefing, edit Watchlist, edit Positions,
  Run button (Section 5).
- Minimal first-run onboarding + disclaimer (Section 6).
- Security & build hygiene checklist (Section 7).
- Basic PyInstaller one-folder build + Inno Setup installer (Section 8).

**Optional add-ons (after the core works):**
- Integrations page: BYO AI key, BYO email.
- Daily auto-scheduling via Task Scheduler checkbox.
- Windowed app feel (pywebview).

**Explicitly deferred to the product phase:**
- Broker sync in the distributed app + guided BYO-broker wizard.
- Hosted subscription service, accounts/auth, billing, AI-key proxy with per-user
  metering, multi-tenant data store.
- Code signing, auto-update.

---

## 10. Future product bridge

What carries over when the owner goes subscription: the **FastAPI API and the
frontend lift to the cloud** largely intact. The engine becomes a per-tenant
server-side worker. What gets *added* (not rebuilt): user accounts/auth, billing,
an owner-key AI proxy with per-user metering, a multi-tenant data store replacing
the local profile dir, and the hosted SnapTrade BYO-broker wizard. The desktop beta
and the product share the bottom two layers — the reason Approach A was chosen.

---

## 11. Open items for the build phase

- Exact OS credential-store mechanism (Windows DPAPI via `keyring`) and key names.
- Default beta watchlist contents (reuse the owner's vetted list minus anything
  personal, or a neutral liquid-large-cap starter set).
- Local server port selection + handling a port already in use.
- Inno Setup vs. an alternative installer; icon/branding assets.
- Whether the daily Task Scheduler job runs the engine headless or just launches the
  app.
- Minimum Windows version target for the build.
