# Stock Advisor Packaging — PyInstaller + Inno Setup Installer (Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the local web app into a double-clickable Windows program a non-technical friend can install: a **PyInstaller one-folder build** of the FastAPI server + browser UI, wrapped in an **Inno Setup installer** (Start Menu + desktop shortcut, uninstaller), with a **build-hygiene gate** that guarantees none of the owner's private data (`.env`, secrets, `data/`, `reports/`, real `config/`) is ever bundled.

**Architecture:** No application-code changes — Plan 1/2 already made this possible. `src/app.py` is the entry point; `src/resources.base_path()` already returns `sys._MEIPASS` when frozen, so the bundled `defaults/` and `ui/` resolve inside the package once they're added with `--add-data`. The build is driven by a version-controlled **`StockAdvisor.spec`** (reproducible, not a fragile CLI one-liner) plus thin PowerShell wrappers. A pure-Python **`scripts/verify_build.py`** scans the produced `dist/` and fails the build if any owner-private artifact leaked in — this is the single real owner-side risk (spec §7) and it is enforced mechanically, not by hope. The Inno Setup script packages the `dist/` folder; per the locked decision the **beta has no Task Scheduler job** — the briefing simply runs when the user opens the app.

**Tech Stack:** Python 3, PyInstaller (one-folder, NOT one-file — fewer antivirus false positives, spec §8), Pillow (one-time PNG→multi-resolution `.ico` conversion), Inno Setup 6 (`ISCC.exe` compiler), pytest for the hygiene-verifier unit tests. Console build (not windowed) for the beta: the launcher window shows "running… Ctrl+C to stop", which is the simplest reliable way for a beginner to see it's alive and stop it; a windowed/tray feel is a later polish (spec §5).

**Part of:** `docs/superpowers/specs/2026-06-15-stock-advisor-distribution-design.md` (§7 build hygiene, §8 packaging & distribution). Builds on Plan 1 (engine refactor — `Profile`/`%APPDATA%` profile), Plan 2 (local web app — `src/app.py` launcher, `resources.base_path()` frozen support), and Plan 2b (Integrations — adds the `keyring` dependency that must be bundled). All three are merged to `main`.

**Locked decisions (this session):**
| Decision | Choice |
|---|---|
| Daily run | **Runs when the app opens.** No Windows Task Scheduler job in the beta installer. |
| Toolchain | **PyInstaller one-folder + Inno Setup** installer (requires the free Inno Setup 6 compiler installed on the build machine). |
| Icon | Owner-provided art at **`installer/source-icon.png`** → converted to a multi-resolution `installer/StockAdvisor.ico`. |
| Console | **Console build** (visible launcher window; clear stop mechanism). Windowed/tray deferred. |
| Broker sync | Not surfaced in the beta (Integrations has no broker tab); no SnapTrade creds ship. Code path stays dormant. |

**Where this runs:** the Stock Advisor repo at `C:\VS Code\Stock Advisor`. Do the work on a feature branch (e.g. `packaging`). Activate the venv once per session: `& .\.venv\Scripts\Activate.ps1`. Run commands from the repo root.

**Honest caveats (surface these, don't bury them):**
- PyInstaller builds are **iterative**: hidden/dynamic imports (uvicorn's loop/protocol autodetect, lazily-imported `anthropic`, `pandas_market_calendars` data) often need to be declared before the frozen exe launches cleanly. Task 3 includes a deliberate "run → fix the missing import → repeat" loop. This is normal, not a failure.
- An **unsigned installer trips Windows SmartScreen** ("Windows protected your PC" → More info → Run anyway). Acceptable for friends & family *with a heads-up*; a code-signing cert (~$200–500/yr) is a product-stage decision (spec §8).
- Inno Setup must be installed on the build machine (`winget install JRSoftware.InnoSetup`, or the official installer). Compiling the installer (Task 4) needs `ISCC.exe` on PATH.
- The actual frozen-exe launch + installer run are **verified by a human/CLI on this Windows machine** — they can't be exercised by the unit-test suite. The automated safety net is the hygiene verifier (Task 2), which IS unit-tested.

---

## File Structure

New files:
- **`src/__init__.py`** (modify) — add `__version__ = "0.1.0"`: the single source of truth the build + installer read.
- **`scripts/make_icon.py`** — one-time converter: `installer/source-icon.png` → `installer/StockAdvisor.ico` (sizes 16/24/32/48/64/128/256). One responsibility: *produce the multi-res icon.*
- **`installer/StockAdvisor.ico`** — the generated icon (committed, so the build doesn't depend on Pillow at build time).
- **`scripts/verify_build.py`** — `find_forbidden(dist_dir) -> list[str]` + a CLI `main()` that exits non-zero if the built `dist/` contains owner-private artifacts. One responsibility: *the build-hygiene gate.*
- **`StockAdvisor.spec`** — the PyInstaller build definition (entry script, datas, hidden imports, icon, one-folder COLLECT).
- **`scripts/build_app.ps1`** — wrapper: clean → run PyInstaller on the spec → run the hygiene verifier (fails the build if it flags anything).
- **`installer/StockAdvisor.iss`** — Inno Setup script (app metadata, files = the `dist/StockAdvisor` folder, Start Menu + desktop shortcut, uninstaller; no scheduled task).
- **`scripts/build_installer.ps1`** — wrapper: read `__version__` → invoke `ISCC.exe` with the version → emit `installer/Output/StockAdvisor-Setup-<version>.exe`.
- **`tests/test_verify_build.py`** — unit tests for the hygiene verifier.
- **`docs/RELEASE.md`** — the build & release runbook + the spec §7 hygiene checklist.

Modify:
- **`requirements-build.txt`** (new) — build-only deps (`pyinstaller`, `pillow`) kept out of the runtime `requirements.txt`.
- **`.gitignore`** — ignore PyInstaller's `build/` and `dist/` and Inno's `installer/Output/`.
- **`README.md`** — a short "Install the app (Windows)" + "Build a release" pointer to `docs/RELEASE.md`.

Facts locked in by reading the code (do not re-derive):
- Entry point: `src/app.py` → `main(open_browser=True)` resolves `Profile.for_base(user_base_dir())`, seeds defaults, picks a free port from 8765, runs `uvicorn.run(app, host="127.0.0.1", ...)`, and opens the browser. `python -m src.app` is the dev invocation; the frozen exe runs the same `main()`.
- `src/resources.base_path()` returns `sys._MEIPASS` when frozen else the repo root; `defaults_dir()`/`ui_dir()` hang off it. `tests/test_resources.py::test_base_path_uses_meipass_when_frozen` already proves the frozen branch — so `--add-data` mapping `defaults`→`defaults` and `ui`→`ui` is all that's needed (no code change). DO NOT modify `resources.py`.
- `.gitignore` already excludes `.env`, `.env.bak`, `data/`, `reports/`, `logs/` — these are exactly the owner-private artifacts the verifier must also keep out of the build.
- Bundled `defaults/` holds the sane starter configs (watchlist/weights/adjudicator/exits/positions); the owner's REAL `config/` (their tickers/holdings) must never ship. Secret env-var names that must never appear in the bundle: `ANTHROPIC_API_KEY`, `SNAPTRADE_*`, `EMAIL_PASSWORD`, `FMP_API_KEY`, plus the owner's email.
- `keyring` (Plan 2b) is imported lazily inside `src/secrets_store.py`; PyInstaller's static analysis misses lazy imports, so the Windows backend must be declared (`keyring.backends.Windows` + `collect_submodules('keyring')`).

---

## Task 1: App version + application icon

**Files:**
- Modify: `src/__init__.py`
- Create: `scripts/make_icon.py`
- Create (generated, committed): `installer/StockAdvisor.ico`
- Create: `requirements-build.txt`

- [ ] **Step 1: Add the version constant**

Read `src/__init__.py` first. Append (or set, if empty) exactly:

```python
__version__ = "0.1.0"
```

- [ ] **Step 2: Create the build-only requirements file**

Create `requirements-build.txt`:

```
# Build-time only (NOT needed to run the app from source). Install with:
#   python -m pip install -r requirements-build.txt
pyinstaller>=6.6
pillow>=10.0
```

- [ ] **Step 3: Install the build deps**

Run: `python -m pip install -r requirements-build.txt`
Expected: installs `pyinstaller` and `pillow` (+ their deps). Paste the final "Successfully installed …" line.

- [ ] **Step 4: Write the icon converter**

Create `scripts/make_icon.py`:

```python
"""One-time: convert the owner-provided PNG into a multi-resolution Windows .ico.

Run:  python scripts/make_icon.py
Reads  installer/source-icon.png  ->  writes  installer/StockAdvisor.ico
A multi-size .ico lets Windows pick the crisp variant for the taskbar, Start Menu,
desktop shortcut, and Alt-Tab. The .ico is committed so the build needs no Pillow.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "installer" / "source-icon.png"
OUT = ROOT / "installer" / "StockAdvisor.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    img = Image.open(SRC).convert("RGBA")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="ICO", sizes=SIZES)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Generate the icon**

Run: `python scripts/make_icon.py`
Expected: prints `wrote …\installer\StockAdvisor.ico (<N> bytes)` with N > 0.

- [ ] **Step 6: Verify the .ico is a valid multi-size icon**

Run this one-liner to confirm the sizes embedded:

```
python -c "from PIL import Image; im=Image.open('installer/StockAdvisor.ico'); print(sorted(im.info.get('sizes', [])))"
```
Expected: prints a list including `(256, 256)` and `(16, 16)` (the full set). If it errors or shows a single size, STOP — the conversion failed.

- [ ] **Step 7: Commit**

```bash
git add src/__init__.py scripts/make_icon.py installer/StockAdvisor.ico installer/source-icon.png requirements-build.txt
git commit -m "build: app version, icon converter, generated .ico, build-only deps"
```

---

## Task 2: Build-hygiene verifier (the safety gate)

**Files:**
- Create: `scripts/verify_build.py`
- Test: `tests/test_verify_build.py`

This is the most important task: it mechanically guarantees spec §7's "nothing personal in the package."

- [ ] **Step 1: Write the failing tests**

Create `tests/test_verify_build.py`:

```python
from pathlib import Path

from scripts.verify_build import find_forbidden


def _touch(p: Path, text: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_clean_bundle_has_no_problems(tmp_path):
    # A legit one-folder build: exe + _internal with bundled defaults + ui.
    _touch(tmp_path / "StockAdvisor.exe")
    _touch(tmp_path / "_internal" / "defaults" / "watchlist.yaml", "tickers:\n  - AAPL\n")
    _touch(tmp_path / "_internal" / "defaults" / "positions.yaml", "positions: []\n")
    _touch(tmp_path / "_internal" / "ui" / "index.html", "<html></html>")
    _touch(tmp_path / "_internal" / "base_library.zip")
    assert find_forbidden(tmp_path) == []


def test_flags_bundled_dotenv(tmp_path):
    _touch(tmp_path / "_internal" / ".env", "ANTHROPIC_API_KEY=sk-real\n")
    problems = find_forbidden(tmp_path)
    assert any(".env" in p for p in problems)


def test_flags_secret_marker_in_any_text_file(tmp_path):
    # Even if a config is misnamed, a secret marker in its contents must be caught.
    _touch(tmp_path / "_internal" / "config" / "leak.yaml", "EMAIL_PASSWORD: hunter2\n")
    problems = find_forbidden(tmp_path)
    assert any("EMAIL_PASSWORD" in p for p in problems)


def test_flags_owner_email_marker(tmp_path):
    _touch(tmp_path / "_internal" / "notes.txt", "contact dhodgeman90@gmail.com")
    assert find_forbidden(tmp_path) != []


def test_flags_config_yaml_outside_defaults(tmp_path):
    # The owner's real configs must only ever ship as bundled defaults/.
    _touch(tmp_path / "_internal" / "config" / "positions.yaml",
           "positions:\n  - ticker: AAPL\n    entry_price: 100\n")
    problems = find_forbidden(tmp_path)
    assert any("positions.yaml" in p for p in problems)


def test_allows_config_yaml_inside_defaults(tmp_path):
    _touch(tmp_path / "_internal" / "defaults" / "exits.yaml", "defaults: {}\nbacktest: {}\n")
    assert find_forbidden(tmp_path) == []


def test_flags_data_and_reports_dirs(tmp_path):
    _touch(tmp_path / "_internal" / "reports" / "2026-06-16.md", "briefing")
    _touch(tmp_path / "_internal" / "data" / "wsb_cache.json", "{}")
    problems = find_forbidden(tmp_path)
    assert any("reports" in p for p in problems)
    assert any("data" in p for p in problems)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_verify_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.verify_build'` (and `scripts` needs to be importable — see Step 3).

- [ ] **Step 3: Implement the verifier**

Create `scripts/verify_build.py`:

```python
"""Build-hygiene gate (spec §7): fail the build if the produced dist/ contains any of
the owner's private artifacts. The shipped app must contain ZERO personal data.

find_forbidden(dist_dir) returns a list of human-readable problems ([] == clean).
Run as a CLI after PyInstaller:  python scripts/verify_build.py dist/StockAdvisor
Exits 1 (and prints the problems) if anything leaked, so build_app.ps1 aborts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Secret env-var names / owner identifiers that must NEVER appear in a shipped file.
SECRET_MARKERS = (
    "ANTHROPIC_API_KEY", "SNAPTRADE_", "EMAIL_PASSWORD", "FMP_API_KEY",
    "dhodgeman90@gmail.com",
)
# Files that are private regardless of where they sit in the tree.
FORBIDDEN_FILENAMES = (".env", ".env.bak")
# Runtime dirs that hold the owner's generated data and must never be bundled.
FORBIDDEN_DIR_NAMES = ("data", "reports", "logs")
# Project config files that may ONLY ship as bundled defaults (under a 'defaults' dir).
CONFIG_BASENAMES = (
    "watchlist.yaml", "positions.yaml", "exits.yaml", "weights.yaml",
    "adjudicator.yaml", "signals.yaml", "integrations.yaml",
)
# Only scan small text-ish files for secret markers (skip big binaries/wheels).
TEXT_SUFFIXES = (".env", ".yaml", ".yml", ".json", ".txt", ".cfg", ".ini", ".md")


def find_forbidden(dist_dir) -> list[str]:
    dist = Path(dist_dir)
    problems: list[str] = []
    for p in dist.rglob("*"):
        rel = p.relative_to(dist)
        if p.is_dir():
            if p.name in FORBIDDEN_DIR_NAMES:
                problems.append(f"private runtime dir bundled: {rel}")
            continue
        if p.name in FORBIDDEN_FILENAMES:
            problems.append(f"env/secret file bundled: {rel}")
            continue
        if p.name in CONFIG_BASENAMES and "defaults" not in rel.parts:
            problems.append(f"non-default project config bundled: {rel}")
        if p.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for marker in SECRET_MARKERS:
                if marker in text:
                    problems.append(f"secret marker {marker!r} found in {rel}")
                    break
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/verify_build.py <dist_dir>")
        return 2
    problems = find_forbidden(argv[1])
    if problems:
        print("BUILD HYGIENE FAILED — owner-private artifacts found in the bundle:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("build hygiene OK — no owner-private artifacts in the bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

Note on importability: the repo's pytest rootdir puts the project root on `sys.path` (tests already do `from src.x import y`). Confirm `from scripts.verify_build import find_forbidden` resolves; if `scripts/` lacks an `__init__.py` and the import fails, add an empty `scripts/__init__.py` and include it in the commit. (Check first — do not add it if the import already resolves.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_verify_build.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS (prior count + 7 new).

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_build.py tests/test_verify_build.py
# include scripts/__init__.py only if you had to add it:
# git add scripts/__init__.py
git commit -m "feat: build-hygiene verifier (fail build on bundled owner-private data)"
```

---

## Task 3: PyInstaller spec + build (iterative until the frozen exe runs)

**Files:**
- Create: `StockAdvisor.spec`
- Create: `scripts/build_app.ps1`
- Modify: `.gitignore`

- [ ] **Step 1: Ignore build output**

Append to `.gitignore`:

```
# packaging build output
build/
dist/
installer/Output/
*.exe
```

- [ ] **Step 2: Write the PyInstaller spec**

Create `StockAdvisor.spec` (a normal PyInstaller spec — run via `pyinstaller StockAdvisor.spec`):

```python
# -*- mode: python ; coding: utf-8 -*-
"""One-folder build of the Stock Advisor local app.

Entry point is src/app.py (the same launcher as `python -m src.app`). defaults/ and
ui/ are bundled at the _MEIPASS root so resources.base_path() finds them when frozen.
Lazy/dynamic imports (keyring's OS backend, uvicorn's loop/protocol autodetect, the
lazily-imported anthropic SDK) are declared explicitly because PyInstaller's static
analysis cannot see them.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
hiddenimports += collect_submodules("keyring")          # OS credential store backends
hiddenimports += collect_submodules("uvicorn")          # loop/protocol autodetect
hiddenimports += ["anthropic"]                           # imported lazily when AI is on

datas = [("defaults", "defaults"), ("ui", "ui")]
datas += collect_data_files("pandas_market_calendars")   # bundled NYSE calendar data

a = Analysis(
    ["src/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockAdvisor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX off: it raises antivirus false positives
    console=True,                    # visible launcher window (clear stop = close it)
    icon="installer/StockAdvisor.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StockAdvisor",
)
```

- [ ] **Step 3: Write the build wrapper**

Create `scripts/build_app.ps1`:

```powershell
# Build the one-folder app and gate it on the hygiene verifier.
# Run from the repo root with the venv active:  .\scripts\build_app.ps1
$ErrorActionPreference = "Stop"

Write-Host "Cleaning previous build..."
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }

Write-Host "Running PyInstaller..."
pyinstaller StockAdvisor.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host "Verifying build hygiene..."
python scripts/verify_build.py dist/StockAdvisor
if ($LASTEXITCODE -ne 0) { throw "BUILD HYGIENE FAILED - see problems above. Build rejected." }

Write-Host "Build OK -> dist\StockAdvisor\StockAdvisor.exe"
```

- [ ] **Step 4: Run the build**

Run: `.\scripts\build_app.ps1`
Expected: PyInstaller produces `dist/StockAdvisor/StockAdvisor.exe` and the hygiene verifier prints "build hygiene OK". If PyInstaller errors, fix and re-run.

- [ ] **Step 5: Launch the frozen exe and smoke-test it (the iterative loop)**

This is where dynamic-import gaps surface. Start the built exe (it starts the server + opens a browser):

```powershell
Start-Process dist\StockAdvisor\StockAdvisor.exe
Start-Sleep -Seconds 6
```

Then verify the server answers (the launcher picks a free port from 8765 — try 8765 first; if the owner's dev server isn't running it will be 8765):

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/state
```

Expected: JSON like `{"disclaimer_accepted": false}` (a fresh `%APPDATA%\StockAdvisor` profile is seeded on first run).

**If the exe exits immediately or the request fails:** read the console window / run the exe directly in a terminal to see the traceback. The usual cause is a missing dynamic import — e.g. `ModuleNotFoundError: No module named 'uvicorn.loops.auto'` or an `anthropic`/`pandas_market_calendars` submodule. Fix by adding the named module to `hiddenimports` (or the relevant `collect_submodules`/`collect_data_files`) in `StockAdvisor.spec`, rebuild (Step 4), and retry (Step 5). **Repeat until `/api/state` answers.** This loop is expected for PyInstaller; don't treat the first failure as a dead end.

- [ ] **Step 6: Full functional smoke (real briefing through the frozen app)**

With the exe running, exercise an end-to-end run (this fetches live market data — ~30s):

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/run
Invoke-RestMethod http://127.0.0.1:8765/api/briefing/today
```

Expected: the POST returns a status (`ok`/`skipped`), and the GET returns the briefing HTML (or a `status: none` if skipped). Confirm a `reports\` + `data\` folder appeared under `%APPDATA%\StockAdvisor`, NOT inside the install/dist folder (proves profile isolation holds in the frozen app). Then stop the exe:

```powershell
Get-Process StockAdvisor -ErrorAction SilentlyContinue | Stop-Process -Force
```

- [ ] **Step 7: Re-run the hygiene verifier on the final dist (belt-and-suspenders)**

Run: `python scripts/verify_build.py dist/StockAdvisor`
Expected: "build hygiene OK". (If it ever flags something — e.g. a hook swept in a stray file — STOP and fix the spec; do not ship.)

- [ ] **Step 8: Commit (spec + build script + gitignore only — never the dist/)**

```bash
git add StockAdvisor.spec scripts/build_app.ps1 .gitignore
git commit -m "build: PyInstaller one-folder spec + hygiene-gated build script"
```
Confirm `git status` shows no `dist/` or `build/` staged (they're git-ignored).

> If Step 5/6 required adding hidden imports, those edits are in `StockAdvisor.spec` and are included above. Note in your report exactly which imports you had to add — Plan 3's reviewer and `docs/RELEASE.md` should record them.

---

## Task 4: Inno Setup installer

**Files:**
- Create: `installer/StockAdvisor.iss`
- Create: `scripts/build_installer.ps1`

Prerequisite: Inno Setup 6 installed (`winget install JRSoftware.InnoSetup` or https://jrsoftware.org/isdl.php). The compiler is `ISCC.exe` (typically `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

- [ ] **Step 1: Write the Inno Setup script**

Create `installer/StockAdvisor.iss`:

```iss
; Inno Setup script for Stock Advisor (one-folder PyInstaller build).
; Version is passed in by build_installer.ps1:  ISCC.exe /DAppVersion=0.1.0 ...
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Stock Advisor"
#define AppExe "StockAdvisor.exe"
#define AppPublisher "Stock Advisor"

[Setup]
AppId={{B2D9F0C2-7A1E-4E8B-9C3A-STOCKADVISOR01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\StockAdvisor
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=StockAdvisor-Setup-{#AppVersion}
SetupIconFile=StockAdvisor.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install -> no admin prompt, simplest for a non-technical tester.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The entire PyInstaller one-folder output. Source is resolved relative to this .iss,
; which lives in installer/, so dist is one level up.
Source: "..\dist\StockAdvisor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Description: "Launch Stock Advisor"; Filename: "{app}\{#AppExe}"; Flags: nowait postinstall skipifsilent
```

Note: the per-user profile and data live in `%APPDATA%\StockAdvisor` (created on first run), entirely separate from `{app}`. The uninstaller removes the program files only — that's correct; the user's data/settings intentionally survive an uninstall/reinstall.

- [ ] **Step 2: Write the installer build wrapper**

Create `scripts/build_installer.ps1`:

```powershell
# Compile the Inno Setup installer. Requires the one-folder build (run build_app.ps1 first)
# and Inno Setup 6 (ISCC.exe). Run from the repo root:  .\scripts\build_installer.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path dist\StockAdvisor\StockAdvisor.exe)) {
    throw "No build found. Run .\scripts\build_app.ps1 first."
}

# Read __version__ from src/__init__.py (single source of truth).
$version = (python -c "import src; print(src.__version__)").Trim()
if (-not $version) { throw "Could not read src.__version__" }

# Locate ISCC.exe.
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $guess = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $guess) { $iscc = $guess } else {
        throw "ISCC.exe not found. Install Inno Setup 6 (winget install JRSoftware.InnoSetup)."
    }
}
$isccPath = if ($iscc -is [System.Management.Automation.CommandInfo]) { $iscc.Source } else { $iscc }

Write-Host "Compiling installer for v$version..."
& $isccPath "/DAppVersion=$version" installer\StockAdvisor.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }

Write-Host "Installer -> installer\Output\StockAdvisor-Setup-$version.exe"
```

- [ ] **Step 3: Build the installer**

Run: `.\scripts\build_installer.ps1`
Expected: `installer\Output\StockAdvisor-Setup-0.1.0.exe` is produced. (If `ISCC.exe` is missing, install Inno Setup 6 first — this step needs it; it's the one external tool the owner installs once.)

- [ ] **Step 4: Verify the installer end-to-end (human/CLI on this machine)**

This is a real install test — do it deliberately:
1. Run `installer\Output\StockAdvisor-Setup-0.1.0.exe`. (SmartScreen may warn on the unsigned exe → More info → Run anyway — expected.)
2. Complete the wizard (per-user, no admin prompt). Confirm a Start Menu entry "Stock Advisor" and, if chosen, a desktop shortcut with the icon.
3. Launch from the shortcut → the console window appears and the browser opens to the dashboard → accept the disclaimer → the four screens work, Integrations shows the real forms (Plan 2b).
4. Confirm the install folder (`%LOCALAPPDATA%\Programs\StockAdvisor` or the chosen dir) contains **no** `.env`, `data/`, `reports/` — only program files + `_internal\defaults` + `_internal\ui`.
5. Uninstall via "Add or remove programs" → program files removed; confirm `%APPDATA%\StockAdvisor` (user data) is intentionally left behind.

Record the outcome. If any step fails, STOP and report — do not ship a broken installer.

- [ ] **Step 5: Commit (installer script + wrapper; never the Output/ exe)**

```bash
git add installer/StockAdvisor.iss scripts/build_installer.ps1
git commit -m "build: Inno Setup installer (Start Menu + desktop shortcut, uninstaller)"
```
Confirm `git status` shows no `installer/Output/` staged.

---

## Task 5: Release runbook + docs + final verification

**Files:**
- Create: `docs/RELEASE.md`
- Modify: `README.md`

- [ ] **Step 1: Write the release runbook + hygiene checklist**

Create `docs/RELEASE.md`:

```markdown
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
```

- [ ] **Step 2: Add user-facing install notes to the README**

In `README.md`, add (near the "Run the local app" section):

```markdown
## Install the app (Windows)

Non-developers can run Stock Advisor without Python:
1. Run `StockAdvisor-Setup-<version>.exe`. If Windows shows "Windows protected your PC",
   click **More info -> Run anyway** (the installer is unsigned during the beta).
2. Launch **Stock Advisor** from the Start Menu (or the desktop shortcut). A small window
   opens and your browser shows the dashboard. Keep that window open while you use the app;
   close it to stop.
3. All your data stays on your machine in `%APPDATA%\StockAdvisor`. Optional AI/email setup
   lives on the Integrations screen (see "Integrations (optional)" above).

Developers building a release: see `docs/RELEASE.md`.
```

- [ ] **Step 3: Full test suite (nothing regressed)**

Run: `pytest -q`
Expected: PASS — same as after Task 2 (docs/scripts don't change runtime behavior).

- [ ] **Step 4: Commit**

```bash
git add docs/RELEASE.md README.md
git commit -m "docs: release runbook + hygiene checklist + Windows install notes"
```

---

## Completion

After all tasks pass and the installer is verified on this machine:
- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch — verify the suite, present merge/PR options (Plans 1, 2, 2b were fast-forward merged to `main`).
- This is the **final plan of the distribution effort.** After merge, the deliverable is `installer\Output\StockAdvisor-Setup-<version>.exe` — the standalone app the owner can hand to friends & family (rules-only by default; AI/email opt-in via Integrations; broker sync still product-phase per spec §9).

---

## Self-Review (done while writing)

**Spec coverage:** PyInstaller one-folder, no UPX (§8) ✓; Inno Setup installer with Start Menu + desktop shortcut + uninstaller (§8) ✓; **no Task Scheduler in beta** (locked decision; §8 "default behavior is simplest") ✓; build-hygiene clean-tree enforced mechanically (§7) ✓ (Task 2 verifier + Task 3 gate); per-user `%APPDATA%` profile isolation re-verified in the frozen app (Task 3 Step 6) ✓; secrets/credential-store ship-nothing (§7) ✓ (verifier markers); icon/branding (§11 open item) ✓; SmartScreen + manual-update frictions surfaced, not hidden (§8) ✓; `--add-data defaults/ + ui/` so `resources.base_path()` resolves when frozen ✓; `keyring` backend bundled for Plan 2b ✓.

**Placeholder scan:** none — every code/test step has complete content; the one inherently-iterative step (Task 3 Step 5, hidden imports) is explicitly called out as a loop with the exact diagnostic + fix procedure, not a vague "handle errors."

**Type/name consistency:** `find_forbidden(dist_dir)` + the constant names (`SECRET_MARKERS`, `FORBIDDEN_FILENAMES`, `FORBIDDEN_DIR_NAMES`, `CONFIG_BASENAMES`, `TEXT_SUFFIXES`) consistent between Task 2's tests and implementation; `installer/StockAdvisor.ico` produced in Task 1 and consumed by `StockAdvisor.spec` (Task 3) + `StockAdvisor.iss` (Task 4); `__version__` defined in Task 1 and read by `build_installer.ps1` (Task 4) + RELEASE.md (Task 5); `dist/StockAdvisor` produced by Task 3 and consumed by Tasks 3 (verify), 4 (installer Source). Build output paths (`dist/`, `build/`, `installer/Output/`) git-ignored in Task 3 and never committed (Tasks 3/4 confirm).

**Note for executor:** Tasks 1–2 are fully automatable/TDD. Tasks 3–4 require running real builds on this Windows machine (and Inno Setup installed for Task 4); their verification is CLI/human, gated by the automated hygiene verifier. Don't dispatch Tasks 3–4 expecting pure unit-test green — the evidence is "the frozen exe serves `/api/state` and a real briefing, and the verifier passes."
```