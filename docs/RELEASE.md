# Building & Releasing Stock Advisor (Windows beta)

One-time setup on the build machine:
- `python -m pip install -r requirements-build.txt`  (PyInstaller + Pillow)
- Install Inno Setup 6: `winget install JRSoftware.InnoSetup`

## Build a release
1. Bump `__version__` in `src/__init__.py` (e.g. `0.1.0` -> `0.1.1`).
2. `& .\.venv\Scripts\Activate.ps1`
3. `.\scripts\build_app.ps1`        # PyInstaller one-folder + hygiene gate
4. `.\scripts\build_installer.ps1`  # -> installer\Output\StockAdvisor-Setup-<version>.exe
5. Smoke-test the installer (install, launch, run a briefing, uninstall).
6. Send `StockAdvisor-Setup-<version>.exe` to the tester with the SmartScreen heads-up below.

## Build-hygiene checklist (spec §7 — non-negotiable)
The shipped package must contain ZERO personal data. `scripts/build_app.ps1` runs
`scripts/verify_build.py`, which FAILS the build if it finds any of:
- `.env` / `.env.bak` anywhere in the bundle
- `data/`, `reports/`, or `logs/` directories
- project config YAML (watchlist/positions/exits/…) outside the bundled `defaults/`
- a secret marker (`ANTHROPIC_API_KEY`, `SNAPTRADE_`, `EMAIL_PASSWORD`, `FMP_API_KEY`,
  the owner's email) in any text file
If the verifier ever fails, the build is rejected — fix the spec, never override the gate.

## Known frictions (tell the tester)
- **SmartScreen:** the installer is unsigned, so Windows shows "Windows protected your
  PC." Tester clicks **More info -> Run anyway**. A code-signing cert removes this and is
  a product-stage decision.
- **First launch:** a console window stays open ("running… Ctrl+C to stop") and the
  browser opens to the dashboard. Closing the console window stops the app.
- **Updates:** manual for the beta — send the next `…-Setup-<version>.exe`. The user's
  data in `%APPDATA%\StockAdvisor` carries over.
