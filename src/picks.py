"""Structured pick ledger — an append-only JSONL record of every daily recommendation,
so the scorecard can later grade how each pick actually performed against the market.

One record per ranked (non-vetoed) candidate per run. Idempotent on (date, ticker,
source): re-running the same day (e.g. clicking the web "Run" button twice) never
double-logs a name. JSONL over a database on purpose — append-only, human-readable, no
schema/migration, stdlib `json` only.
"""
from __future__ import annotations

import json
from pathlib import Path

from src import rotation

LEDGER_NAME = "picks.jsonl"


def ledger_path(data_dir) -> Path:
    return Path(data_dir) / LEDGER_NAME


def load_picks(data_dir) -> list[dict]:
    """Every logged pick, oldest first. A corrupt line is skipped, not fatal."""
    path = ledger_path(data_dir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue   # ponytail: tolerate a half-written line rather than crash the scorecard
    return out


def _key(rec: dict) -> tuple:
    return (rec.get("date"), rec.get("ticker"), rec.get("source", "briefing"))


def _entry_close(df):
    """Latest close from a scored ticker's OHLCV frame, or None if unavailable."""
    if df is None or len(df) == 0:
        return None
    try:
        return round(float(df["Close"].iloc[-1]), 4)
    except Exception:
        return None


def append_records(records: list[dict], data_dir) -> int:
    """Append records whose (date,ticker,source) isn't already in the ledger. Returns
    the number actually written. The shared write path for both live logging and the
    report backfill, so both are idempotent the same way."""
    path = ledger_path(data_dir)
    existing = {_key(r) for r in load_picks(data_dir)}
    new_lines = []
    for rec in records:
        k = _key(rec)
        if k in existing:
            continue
        existing.add(k)
        new_lines.append(json.dumps(rec))
    if new_lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
    return len(new_lines)


def log_picks(ranked, df_by_ticker, data_dir, date_str, *, source="briefing") -> int:
    """Append one record per ranked pick with its entry close. Returns count written.

    `ranked` are the adjudicated buy-candidate dicts (already vetoes-removed) from a run;
    `df_by_ticker` maps ticker -> the OHLCV frame whose last close is that day's price.
    """
    records = []
    for r in ranked:
        ticker = r["ticker"]
        records.append({
            "date": date_str,
            "ticker": ticker,
            "final_score": round(float(r["final_score"]), 1),
            "base_score": round(float(r.get("base_score", r["final_score"])), 1),
            "conviction": rotation._add_conviction(r),
            "entry_close": _entry_close(df_by_ticker.get(ticker)),
            # Which adjudicator caps fired on this pick, for per-signal scorecard
            # attribution. Empty for report-backfilled picks (the .md has no detail).
            "signals": [d.get("key") for d in (r.get("adjustment_detail") or []) if d.get("key")],
            "source": source,
        })
    return append_records(records, data_dir)
