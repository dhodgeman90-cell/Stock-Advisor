"""Point-in-time capture of every raw signal value the daily run computes.

Why this exists: analyst ratings, options flow, short interest, WSB mentions and congress
state are only available as PRESENT-DAY snapshots. No vendor sells their history at the free
tier (FMP's per-symbol congress/insider endpoints return 402; the House/Senate StockWatcher
archives 403), which means none of them can ever be backtested from archived data. But the
briefing already fetches all of them every morning for ~25 candidates and then discards them.

`picks.jsonl` kept only the NAMES of adjudicator caps that fired, and only on some rows —
enough to say "congress_buy fired", never enough to ask "does a congress buy of this size,
this fresh, predict anything?". This stores the raw dicts verbatim, because we do not yet
know which fields matter and guessing now would throw away the experiment.

One record per (date, ticker) over the enriched shortlist — not just the displayed top-8, so
the cross-section is ~25 wide instead of 8. Idempotent like picks.append_records. Every
failure path is swallowed by the caller: a logging hiccup must never break the briefing.
"""
import datetime as dt
import json
from pathlib import Path

HISTORY_FILE = "signal_history.jsonl"
AI_HISTORY_FILE = "ai_history.jsonl"


def history_path(data_dir) -> Path:
    return Path(data_dir) / HISTORY_FILE


def ai_history_path(data_dir) -> Path:
    return Path(data_dir) / AI_HISTORY_FILE


def load_signals(data_dir) -> list:
    path = history_path(data_dir)
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
            continue   # ponytail: tolerate a torn last line rather than lose the history
    return out


def _key(rec: dict) -> tuple:
    return (rec.get("date"), rec.get("ticker"))


def log_signals(cand_rows, data_dir, date_str, *, context=None, cohort="candidate") -> int:
    """Append one record per enriched candidate. Returns the number written.

    `cand_rows` is main.run's list of (scored_row, signals, projected_score). `context` is the
    once-a-day market state (regime, breadth, macro) copied onto every row so a later study can
    condition on it without a second join.

    `cohort` separates the two samples, and the distinction is the whole point:
      "candidate" — the enriched shortlist, chosen by the legacy technical score. That score
                    measures IC ~ 0 but is not RANDOM: it selects names at 20-day highs on
                    volume spikes. Anything correlated with breakout or volume is distorted here.
      "control"   — a deterministic random draw from the eligible universe, never recommended
                    and never displayed. The unbiased comparison group that makes cross-sectional
                    inference possible at all.
    """
    existing = {_key(r) for r in load_signals(data_dir)}
    run_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []
    for row in cand_rows:
        scored, sigs, projected = row[0], row[1], row[2]
        rec = {
            "date": date_str,
            # Wall-clock of the capture (UTC). `date` alone cannot say whether the run happened
            # before the open or after the close, and data._drop_incomplete makes that the
            # difference between scoring off yesterday's bar and today's — so a study that
            # anchors forward returns on `date` is silently mixing entry conventions. The pick
            # ledger records the same field plus the exact bar (picks._bar_date).
            "run_at": run_at,
            "ticker": scored.get("ticker"),
            "base_score": scored.get("score"),
            "projected_score": projected,
            "signals": sigs,
            "context": context or {},
            "cohort": cohort,
        }
        k = _key(rec)
        if k in existing:
            continue
        existing.add(k)
        # default=str so an unexpected object (a Timestamp, a numpy scalar) degrades to its
        # repr instead of aborting the whole day's capture.
        lines.append(json.dumps(rec, default=str))
    if lines:
        path = history_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def load_ai(data_dir) -> list:
    path = ai_history_path(data_dir)
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
            continue
    return out


def log_ai(rows, data_dir, date_str, *, context=None) -> int:
    """Capture what the three AI agents said, point-in-time, WITHOUT letting it score.

    The news, risk and social agents produced the most persuasive prose in the whole product
    and drove 223 of 353 "Buy:" verdicts ever printed, on zero validation in either direction.
    They are unvalidated, not refuted, so `ai_mode: measure` keeps them running and out of the
    decision: this file accrues the record that makes "does the news agent actually predict
    anything?" answerable in a few months, joinable to prices by (date, ticker) exactly like
    signal_history.jsonl.

    Same contract as log_signals: idempotent on (date, ticker), tolerant of odd objects, and
    every failure swallowed by the caller so a logging hiccup can never break the briefing.
    """
    existing = {_key(r) for r in load_ai(data_dir)}
    run_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []
    for row in rows:
        rec = {"date": date_str, "run_at": run_at, "context": context or {}, **row}
        k = _key(rec)
        if k in existing:
            continue
        existing.add(k)
        lines.append(json.dumps(rec, default=str))
    if lines:
        path = ai_history_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)
