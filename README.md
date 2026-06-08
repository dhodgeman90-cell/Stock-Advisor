# Stock Advisor

Local, free tool that scans a watchlist and prints/emails a ranked list of
short-term momentum buy candidates. **Suggests only — never trades.**

See the design spec in `docs/superpowers/specs/` for the full picture.

## Phase 1 (this build): deterministic core

### Setup (one time)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run
```powershell
python -m src.main      # scan the watchlist, print + save a ranked report
```

### Test
```powershell
pytest -v
```
