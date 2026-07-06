"""Pick scorecard — grade how the daily briefing's past recommendations ACTUALLY
performed against the market. This is the missing feedback loop: the engine has always
made picks, but nothing measured whether they worked.

Two views, both off the same fetched price history:

  1. Forward return vs SPY (signal quality). For each pick, the % return at +1/+5/+21
     trading days (and to-date) from its entry, plus the same-window SPY return so we can
     report alpha. Answers: does a higher score actually predict a better forward move?

  2. Simulated exit-rule trade (whole-system P&L). Enter at the pick, walk forward
     applying the app's own deterministic exit rules (exits.evaluate_exit) until a
     sell/trim fires or max-hold is hit, and record the realized return. Answers: would
     trading these picks with our stops/targets have made money?

Picks come from the structured ledger (data/picks.jsonl, written live by main.run via
src/picks.py). On first run the ledger is seeded by parsing the existing reports/*.md
briefings — those carry the pick + score but no price, so the entry price is taken from
the fetched history instead.

Methodology notes baked in:
  * Horizons are +N TRADING bars (positional indexing), never calendar deltas — weekends
    and holidays are skipped automatically.
  * Returns use one fetched (auto-adjusted) series for BOTH endpoints, so a split between
    the pick date and today never corrupts the math. The live-logged entry_close is kept
    on the record for reference but is not the return denominator.
  * An immature horizon (not enough bars yet) is None and is EXCLUDED from aggregates —
    never coerced to 0%.
  * SPY's entry index is found independently of the pick's, so two separately-fetched
    frames are never assumed to share rows.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

from src import backtest, config, data, exits, picks
from src.profile import Profile
from src.results import ScorecardResult

# Matches a Top-candidates line in a saved briefing, e.g. "- **AAPL**: 96/100 (base 81)".
# The "## Other scored" section uses a different format and is deliberately not matched.
PICK_RE = re.compile(r"^- \*\*([A-Z][A-Z0-9.\-]*)\*\*:\s*(\d+)/100 \(base (\d+)\)")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")   # report stem; skips backtest-*/scorecard-*

# Forward horizons in trading bars.
HORIZONS = [("1d", 1), ("5d", 5), ("21d", 21)]
BANDS = (">=80", "60-79", "<60")
DD_LOOKBACK = 63                          # trailing bars (~3 months) defining the "recent high"
DD_BANDS = ("0 to -3%", "-3 to -10%", "<-10%")   # how far below that high the pick was bought
_EXIT_LEVELS = {"sell", "trim"}   # signal levels that close a simulated trade


# --------------------------------------------------------------------------- backfill

def parse_report(text: str, date_str: str) -> list[dict]:
    """Pick records from one saved briefing's '## Top candidates' section. Pure."""
    records = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == "## Top candidates"
            continue
        if not in_section:
            continue
        m = PICK_RE.match(line)
        if m:
            ticker, final, base = m.group(1), int(m.group(2)), int(m.group(3))
            records.append({
                "date": date_str,
                "ticker": ticker,
                "final_score": float(final),
                "base_score": float(base),
                "conviction": None,        # not recoverable from the report text
                "entry_close": None,       # no price in the report; grader fetches it
                "source": "report",
            })
    return records


def backfill_from_reports(reports_dir, data_dir) -> int:
    """Seed the ledger from existing reports/<date>.md briefings. Idempotent."""
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return 0
    records = []
    for path in sorted(reports_dir.glob("*.md")):
        if not DATE_RE.match(path.stem):
            continue   # skip backtest-*.md, scorecard-*.md, etc.
        records.extend(parse_report(path.read_text(encoding="utf-8"), path.stem))
    return picks.append_records(records, data_dir)


# ----------------------------------------------------------------- price / return math

def _pos_on_or_after(df, when) -> int | None:
    """Index of the first bar on or after `when` (nearest forward trading day)."""
    if df is None or len(df) == 0:
        return None
    pos = int(df.index.searchsorted(pd.Timestamp(when)))
    return pos if pos < len(df) else None


def forward_return(df, entry_pos, horizon) -> float | None:
    """% change from the entry bar to `horizon` bars later, both from the same series.
    None when the entry is invalid or the horizon bar doesn't exist yet (immature)."""
    if df is None or entry_pos is None:
        return None
    j = entry_pos + horizon
    if j < 0 or j >= len(df):
        return None
    entry = float(df["Close"].iloc[entry_pos])
    if entry <= 0:
        return None
    return (float(df["Close"].iloc[j]) / entry - 1.0) * 100.0


def to_date_return(df, entry_pos) -> float | None:
    """% change from the entry bar to the latest bar."""
    if df is None or entry_pos is None:
        return None
    return forward_return(df, entry_pos, (len(df) - 1) - entry_pos)


def _net_return(entry, exit_price, rules) -> float:
    """Round-trip return (%) after transaction cost — same model as the backtester."""
    raw = (exit_price - entry) / entry * 100
    cost = 2 * float(rules.get("backtest", {}).get("cost_pct_per_side", 0.0))
    return raw - cost


def simulate_exit_from_entry(df, entry_pos, rules) -> dict:
    """View 2: enter at the pick's close, walk forward applying the deterministic exit
    rules until a sell/trim fires or max-hold is hit; force-mark 'open' at end of data.

    Reuses exits.evaluate_exit (the same signals the live briefing shows for holdings).
    """
    n = len(df)
    entry_price = float(df["Close"].iloc[entry_pos])
    if entry_price <= 0:
        return {"status": "error", "return_pct": None}
    max_hold = int(rules.get("backtest", {}).get("max_hold_days", 250))
    peak = entry_price
    i = entry_pos + 1
    while i < n:
        peak = max(peak, float(df["Close"].iloc[i]))
        window = df.iloc[: i + 1]
        position = {"ticker": "_", "entry_price": entry_price, "peak_price": peak}
        ev = exits.evaluate_exit(window, position, rules)
        held = i - entry_pos
        signalled = any(s["level"] in _EXIT_LEVELS for s in ev["signals"])
        if signalled or held >= max_hold:
            exit_price = float(df["Close"].iloc[i])
            reason = (next(s["type"] for s in ev["signals"] if s["level"] in _EXIT_LEVELS)
                      if signalled else "max_hold")
            return {"status": "closed", "reason": reason, "hold_days": held,
                    "return_pct": _net_return(entry_price, exit_price, rules),
                    "exit_date": str(df.index[i].date())}
        i += 1
    # Never triggered an exit — still open at the end of available data.
    held = max((n - 1) - entry_pos, 0)
    exit_price = float(df["Close"].iloc[-1])
    return {"status": "open", "reason": "open", "hold_days": held,
            "return_pct": _net_return(entry_price, exit_price, rules) if held else 0.0,
            "exit_date": str(df.index[-1].date())}


def _band(score) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return ">=80"
    if score >= 60:
        return "60-79"
    return "<60"


def _drawdown_from_high(df, entry_pos, lookback=DD_LOOKBACK) -> float | None:
    """% the entry close sits below the highest close in the trailing `lookback` bars —
    0 at a fresh high, negative when the pick was bought into a dip. None when there is no
    prior bar to judge against (entry is the first bar of the series)."""
    if df is None or entry_pos is None or entry_pos < 1:
        return None
    lo = max(0, entry_pos - lookback + 1)
    high = float(df["Close"].iloc[lo:entry_pos + 1].max())
    if high <= 0:
        return None
    return (float(df["Close"].iloc[entry_pos]) / high - 1.0) * 100.0


def _dd_band(dd) -> str:
    if dd is None:
        return "unknown"
    if dd >= -3:
        return "0 to -3%"
    if dd >= -10:
        return "-3 to -10%"
    return "<-10%"


def grade_pick(pick, df, spy_df, rules) -> dict:
    """Grade one pick: forward returns + SPY alpha (view 1) and an exit-rule sim (view 2)."""
    out = {
        "date": pick["date"], "ticker": pick["ticker"],
        "final_score": pick.get("final_score"), "conviction": pick.get("conviction"),
        "band": _band(pick.get("final_score")), "logged_entry": pick.get("entry_close"),
        "signals": list(pick.get("signals") or []),   # adjudicator caps that fired (for attribution)
    }
    entry_pos = _pos_on_or_after(df, pick["date"])
    if df is None or entry_pos is None:
        out["error"] = "no price data" if df is None else "pick date after last bar"
        return out

    out["entry"] = round(float(df["Close"].iloc[entry_pos]), 4)
    out["entry_date"] = str(df.index[entry_pos].date())
    dd = _drawdown_from_high(df, entry_pos)
    out["drawdown_from_high"] = dd            # entry vs its trailing 63-bar high (timing signal)
    out["dd_band"] = _dd_band(dd)

    spy_pos = _pos_on_or_after(spy_df, pick["date"])
    for label, h in HORIZONS:
        r = forward_return(df, entry_pos, h)
        out[f"ret_{label}"] = r
        sr = forward_return(spy_df, spy_pos, h)
        out[f"alpha_{label}"] = (r - sr) if (r is not None and sr is not None) else None
    rtd = to_date_return(df, entry_pos)
    srtd = to_date_return(spy_df, spy_pos)
    out["ret_todate"] = rtd
    out["alpha_todate"] = (rtd - srtd) if (rtd is not None and srtd is not None) else None

    out["sim"] = simulate_exit_from_entry(df, entry_pos, rules)
    return out


# ------------------------------------------------------------------------- aggregation

def _avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _beat_rate(alphas):
    alphas = [a for a in alphas if a is not None]
    if not alphas:
        return None
    return sum(1 for a in alphas if a > 0) / len(alphas) * 100


def _as_trades(rows, ret_key):
    """Adapt graded rows into the {return_pct, reason, hold_days} shape backtest.summarize
    consumes, so we get win_rate/avg_gain/avg_loss/expectancy for free."""
    return [{"return_pct": r[ret_key], "reason": r.get("band", "?"), "hold_days": 0}
            for r in rows if r.get(ret_key) is not None]


def summarize_scorecard(graded, ret_key="ret_5d", alpha_key="alpha_5d",
                        buy_threshold=None) -> dict:
    """Aggregate the forward-return view at one horizon: overall, by score band, by
    conviction, and (when a buy threshold is given) the actionable cohort at/above it."""
    rows = [g for g in graded if not g.get("error")]
    matured = [g for g in rows if g.get(ret_key) is not None]

    def block(subset):
        alphas = [g.get(alpha_key) for g in subset]
        return {
            "summary": backtest.summarize(_as_trades(subset, ret_key)),
            "avg_alpha": _avg(alphas),
            "beat_spy_rate": _beat_rate(alphas),
            "n": len(subset),
        }

    by_band = {b: block([g for g in matured if g.get("band") == b]) for b in BANDS}
    by_conviction = {c: block([g for g in matured if g.get("conviction") == c])
                     for c in ("high", "normal")
                     if any(g.get("conviction") == c for g in matured)}
    by_drawdown = {b: block([g for g in matured if g.get("dd_band") == b]) for b in DD_BANDS}
    cohort = None
    if buy_threshold is not None:
        cohort = block([g for g in matured if (g.get("final_score") or 0) >= buy_threshold])
        cohort["threshold"] = buy_threshold

    overall = block(matured)
    return {
        "ret_key": ret_key, "n_total": len(rows), "n_matured": len(matured),
        "overall": overall, "by_band": by_band, "by_conviction": by_conviction,
        "by_drawdown": by_drawdown, "cohort": cohort,
    }


def _first_per_ticker(graded) -> list:
    """Each ticker's EARLIEST recommendation only. The ledger is oldest-first, so keeping
    the first time a ticker appears gives independent observations — it strips the daily
    re-recommendation overlap (a name re-listed every morning would otherwise count a
    single sustained move many times)."""
    seen = set()
    out = []
    for g in graded:
        t = g.get("ticker")
        if t in seen:
            continue
        seen.add(t)
        out.append(g)
    return out


def summarize_sim(graded) -> dict:
    """Aggregate the exit-rule simulation (view 2) across all picks with a result."""
    sims = [g["sim"] for g in graded
            if g.get("sim") and g["sim"].get("return_pct") is not None]
    trades = [{"return_pct": s["return_pct"], "hold_days": s.get("hold_days", 0),
               "reason": s.get("reason", "open")} for s in sims]
    return {
        "summary": backtest.summarize(trades),
        "closed": sum(1 for s in sims if s.get("status") == "closed"),
        "open": sum(1 for s in sims if s.get("status") == "open"),
    }


# Below this many matured fires, a per-signal alpha reading is too noisy to trust — it is
# reported as "insufficient" rather than as a number that invites overfitting (the exact
# trap that produced the inverted top band). Raise it as the ledger grows.
MIN_SIGNAL_FIRES = 20


def summarize_by_signal(graded, alpha_key="alpha_5d", ret_key="ret_5d",
                        min_fires=MIN_SIGNAL_FIRES) -> dict:
    """Per-signal forward-alpha attribution: for each adjudicator cap that fired, the avg
    forward alpha of matured picks where it fired vs where it did NOT. This is what turns
    "the score is inverted at the top" into an actionable cut-list — a cap whose fired
    alpha is reliably below its not-fired alpha is subtracting value.

    A signal with fewer than `min_fires` matured fires is flagged `insufficient` (n only),
    never scored — a thin sample is noise, not evidence.
    """
    matured = [g for g in graded if not g.get("error") and g.get(alpha_key) is not None]
    keys = sorted({k for g in matured for k in (g.get("signals") or [])})
    out = {}
    for key in keys:
        fired = [g for g in matured if key in (g.get("signals") or [])]
        if len(fired) < min_fires:
            out[key] = {"n_fired": len(fired), "insufficient": True}
            continue
        not_fired = [g for g in matured if key not in (g.get("signals") or [])]
        a_fired = _avg([g.get(alpha_key) for g in fired])
        a_not = _avg([g.get(alpha_key) for g in not_fired])
        out[key] = {
            "n_fired": len(fired),
            "insufficient": False,
            "avg_alpha_fired": a_fired,
            "avg_alpha_not_fired": a_not,
            "alpha_delta": (a_fired - a_not) if (a_fired is not None and a_not is not None) else None,
            "avg_ret_fired": _avg([g.get(ret_key) for g in fired]),
        }
    return out


# ---------------------------------------------------------------------------- rendering

def _fmt(v, suffix="%"):
    return "n/a" if v is None else f"{v:+.1f}{suffix}"


def _summary_line(block) -> str:
    s = block["summary"]
    beat = "n/a" if block["beat_spy_rate"] is None else f"{block['beat_spy_rate']:.0f}%"
    return (f"{block['n']} picks · win {s['win_rate']:.0f}% · "
            f"avg {s['avg_trade_return']:+.1f}% · beat SPY {beat} · "
            f"alpha {_fmt(block['avg_alpha'])}")


def render_scorecard_report(result, date_str) -> str:
    graded = result["graded"]
    L = [f"# Stock Advisor — Pick Scorecard ({date_str})", ""]

    err = [g for g in graded if g.get("error")]
    L.append(f"Grading **{len(graded)}** logged picks. "
             f"Forward returns measured in trading days; SPY = same-window benchmark.")
    if err:
        L.append(f"_({len(err)} picks could not be priced and are excluded.)_")
    L.append("")

    # ---- View 1: forward return vs SPY ----
    L.append("## 1) Forward return vs SPY (signal quality)")
    for ret_key, alpha_key, title in (("ret_1d", "alpha_1d", "+1 trading day"),
                                       ("ret_5d", "alpha_5d", "+5 trading days")):
        fwd = result["forward"][ret_key]
        L.append("")
        L.append(f"### {title} — {fwd['n_matured']} of {fwd['n_total']} matured")
        if fwd["cohort"] is not None:
            L.append(f"- **Actionable cohort (score ≥ {fwd['cohort']['threshold']:.0f})**: "
                     f"{_summary_line(fwd['cohort'])}")
        L.append(f"- All picks: {_summary_line(fwd['overall'])}")
        L.append("- By score band:")
        for b in BANDS:
            blk = fwd["by_band"][b]
            if blk["n"]:
                L.append(f"    - {b}: {_summary_line(blk)}")
        if fwd["by_conviction"]:
            L.append("- By conviction:")
            for c, blk in fwd["by_conviction"].items():
                L.append(f"    - {c}: {_summary_line(blk)}")
        dd = fwd.get("by_drawdown", {})
        if any((dd.get(b) or {}).get("n") for b in DD_BANDS):
            L.append("- By drawdown-from-high at entry (did buying dips help?):")
            for b in DD_BANDS:
                blk = dd.get(b)
                if blk and blk["n"]:
                    L.append(f"    - {b}: {_summary_line(blk)}")
    fu = result.get("forward_unique")
    if fu:
        L += ["", f"### Independent picks — first recommendation only ({result.get('n_unique', 0)} names)",
              "_Each name counted once (its earliest rec), so the daily-overlap bias above — a "
              "name re-listed every morning counting one move many times — is removed._"]
        for ret_key, title in (("ret_1d", "+1 trading day"), ("ret_5d", "+5 trading days")):
            f = fu[ret_key]
            L.append(f"- {title} ({f['n_matured']} of {f['n_total']} matured): "
                     f"{_summary_line(f['overall'])}")
            if f["cohort"] is not None and f["cohort"]["n"]:
                L.append(f"    - actionable (score ≥ {f['cohort']['threshold']:.0f}): "
                         f"{_summary_line(f['cohort'])}")

    L.append("")
    L.append("_+21 trading days is still maturing for recent picks; it is shown per-pick "
             "below but omitted from the aggregates above until enough bars exist._")

    # ---- View 2: simulated exit-rule trade ----
    sim = result["sim"]["summary"]
    L += ["", "## 2) Simulated exit-rule trades (whole-system P&L)",
          f"- Closed: **{result['sim']['closed']}** · still open: **{result['sim']['open']}**",
          f"- Win rate: **{sim['win_rate']:.0f}%**  |  avg trade **{sim['avg_trade_return']:+.1f}%**  "
          f"|  expectancy **{sim['expectancy']:+.1f}%**",
          f"- Avg gain **{sim['avg_gain']:+.1f}%**  |  avg loss **{sim['avg_loss']:+.1f}%**  "
          f"|  avg hold **{sim['avg_hold']:.0f}** trading days"]
    if sim["by_reason"]:
        L.append("- Exit reasons: "
                 + ", ".join(f"{r.replace('_', ' ')} ×{n}" for r, n in sim["by_reason"].most_common()))

    # ---- View 3: per-signal attribution ----
    by_signal = result.get("by_signal") or {}
    if by_signal:
        L += ["", "## 3) Signal attribution — which caps actually help? (+5d alpha)",
              "_For each adjudicator cap, avg +5d SPY-alpha of picks where it fired vs where it "
              f"didn't. A cap needs ≥{MIN_SIGNAL_FIRES} fires to be scored; thinner ones are "
              "noise. A negative delta means the signal is SUBTRACTING value — a cut candidate._"]
        scored = {k: v for k, v in by_signal.items() if not v.get("insufficient")}
        thin = {k: v for k, v in by_signal.items() if v.get("insufficient")}
        if scored:
            # Worst (most value-destroying) first — that's the actionable end of the list.
            for key, v in sorted(scored.items(), key=lambda kv: (kv[1].get("alpha_delta") is None,
                                                                 kv[1].get("alpha_delta") or 0)):
                L.append(f"- **{key}** (n={v['n_fired']}): fired {_fmt(v['avg_alpha_fired'])} vs "
                         f"not-fired {_fmt(v['avg_alpha_not_fired'])} → delta {_fmt(v['alpha_delta'])}")
        else:
            L.append("- _No signal has enough fires to score yet — the ledger is still young._")
        if thin:
            L.append("- _Insufficient sample: "
                     + ", ".join(f"{k} (n={v['n_fired']})" for k, v in sorted(thin.items())) + "._")

    # ---- per-pick detail ----
    L += ["", "## Every pick"]
    priced = [g for g in graded if not g.get("error")]
    for g in sorted(priced, key=lambda r: (r["date"], -(r.get("final_score") or 0))):
        sim_g = g.get("sim", {})
        sim_txt = (f"{sim_g.get('return_pct'):+.1f}% [{sim_g.get('reason', '?').replace('_', ' ')}"
                   f"{'' if sim_g.get('status') == 'closed' else ', open'}]"
                   if sim_g.get("return_pct") is not None else "n/a")
        L.append(
            f"- {g['date']} **{g['ticker']}** ({(g.get('final_score') or 0):.0f}/100): "
            f"+1d {_fmt(g.get('ret_1d'))} · +5d {_fmt(g.get('ret_5d'))} · "
            f"+21d {_fmt(g.get('ret_21d'))} · to-date {_fmt(g.get('ret_todate'))} "
            f"(α {_fmt(g.get('alpha_todate'))}) · sim {sim_txt}"
        )
    for g in [g for g in graded if g.get("error")]:
        L.append(f"- {g['date']} **{g['ticker']}**: _{g['error']}_")

    L += ["",
          "> Caveat: a short, recent sample is noisy — a few names can swing the averages. "
          "Read the bands and alpha for signal, not a single number, and let the record grow.",
          "", "_Information only — not financial advice._"]
    return "\n".join(L) + "\n"


def _html_block(title, fwd, ret_key) -> str:
    f = fwd[ret_key]
    head = (f'<tr><th style="text-align:left;padding:4px 10px 4px 0;">{title} '
            f'({f["n_matured"]}/{f["n_total"]} matured)</th>'
            '<th style="padding:4px 10px;">picks</th><th style="padding:4px 10px;">win</th>'
            '<th style="padding:4px 10px;">avg</th><th style="padding:4px 10px;">beat SPY</th>'
            '<th style="padding:4px 10px;">alpha</th></tr>')
    rows = []

    def row(label, blk, bold=False):
        if not blk["n"]:
            return
        s = blk["summary"]
        w = "font-weight:700;" if bold else ""
        beat = "n/a" if blk["beat_spy_rate"] is None else f'{blk["beat_spy_rate"]:.0f}%'
        rows.append(
            f'<tr style="{w}"><td style="padding:3px 10px 3px 0;">{label}</td>'
            f'<td style="text-align:center;">{blk["n"]}</td>'
            f'<td style="text-align:center;">{s["win_rate"]:.0f}%</td>'
            f'<td style="text-align:center;">{s["avg_trade_return"]:+.1f}%</td>'
            f'<td style="text-align:center;">{beat}</td>'
            f'<td style="text-align:center;">{_fmt(blk["avg_alpha"])}</td></tr>')

    if f["cohort"] is not None:
        row(f'Actionable (≥{f["cohort"]["threshold"]:.0f})', f["cohort"], bold=True)
    row("All picks", f["overall"])
    for b in BANDS:
        row(f"band {b}", f["by_band"][b])
    for b in DD_BANDS:
        blk = f.get("by_drawdown", {}).get(b)
        if blk:
            row(f"drawdown {b}", blk)
    return ('<table style="border-collapse:collapse;font-size:13px;margin:6px 0 14px;">'
            + head + "".join(rows) + "</table>")


def render_scorecard_html(result, date_str) -> str:
    """Lightweight styled HTML for the app's Scorecard tab (the .md file is the full report)."""
    graded = result["graded"]
    sim = result["sim"]["summary"]
    P = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1f2937;">',
        f'<div style="font-size:13px;color:#6b7280;margin-bottom:6px;">Grading '
        f'{len(graded)} logged picks · {date_str} · forward returns in trading days, '
        f'benchmarked to SPY.</div>',
        '<div style="font-size:15px;font-weight:700;margin:10px 0 2px;">'
        '1) Forward return vs SPY <span style="font-weight:400;color:#6b7280;font-size:12px;">'
        '(does the score predict the move?)</span></div>',
        _html_block("+1 day", result["forward"], "ret_1d"),
        _html_block("+5 days", result["forward"], "ret_5d"),
    ]
    if result.get("forward_unique"):
        P += [
            f'<div style="font-size:13px;font-weight:700;margin:4px 0 2px;">Independent picks '
            f'<span style="font-weight:400;color:#6b7280;font-size:12px;">'
            f'(each name once — first rec, no daily overlap; {result.get("n_unique", 0)} names)'
            f'</span></div>',
            _html_block("+5 days", result["forward_unique"], "ret_5d"),
        ]
    P += [
        '<div style="font-size:15px;font-weight:700;margin:10px 0 2px;">'
        '2) Simulated exit-rule trades <span style="font-weight:400;color:#6b7280;font-size:12px;">'
        '(would trading them have paid?)</span></div>',
        f'<div style="font-size:13px;margin-bottom:12px;">'
        f'Closed <b>{result["sim"]["closed"]}</b> · open <b>{result["sim"]["open"]}</b> · '
        f'win <b>{sim["win_rate"]:.0f}%</b> · avg trade <b>{sim["avg_trade_return"]:+.1f}%</b> · '
        f'expectancy <b>{sim["expectancy"]:+.1f}%</b> · avg hold <b>{sim["avg_hold"]:.0f}</b>d</div>',
        '<div style="font-size:11.5px;color:#9ca3af;border-top:1px solid #eef0f3;padding-top:10px;">'
        'Short samples are noisy — read the bands and alpha, not a single number. '
        'Information only — not financial advice.</div>',
        '</div>',
    ]
    return "".join(P)


# --------------------------------------------------------------------------------- run

def _load(ticker, days, data_dir, fetch):
    """Fetch history (live) and cache it; fall back to the CSV cache. Honors the injected
    `fetch` so tests stay offline. Mirrors backtest._load_history but uses `fetch`."""
    try:
        df = fetch(ticker, days)
    except Exception:
        df = None
    if df is not None and data.validate(df, ticker)[0]:
        data.save_cache(df, ticker, data_dir)
        return df
    cached = data.load_cache(ticker, data_dir)
    if cached is not None and data.validate(cached, ticker)[0]:
        return cached
    return None


def _grade(profile, fetch):
    """Backfill + load the ledger, fetch each pick ticker's history (+ SPY), and grade
    every pick. Returns (graded, buy_threshold, pick_list). Shared by run() and
    briefing_summary() so both grade identically; neither prints nor writes here.

    ponytail: histories span ledger-oldest + 40 days. If the caller passes a cache-first
    `fetch` (main.run does), tickers it already pulled are reused and only SPY / untracked
    names hit the network — this is why it stays cheap enough to call in the daily hot path.
    """
    backfill_from_reports(profile.reports_dir, profile.data_dir)
    pick_list = picks.load_picks(profile.data_dir)
    rules = config.load_exit_rules(profile.config_dir)
    buy_threshold = float(rules["backtest"]["buy_threshold"])
    if not pick_list:
        return [], buy_threshold, pick_list
    oldest = min(p["date"] for p in pick_list)
    days = (dt.date.today() - dt.date.fromisoformat(oldest)).days + 40
    histories = {}
    for ticker in sorted({p["ticker"] for p in pick_list}):
        df = _load(ticker, days, profile.data_dir, fetch)
        if df is not None:
            histories[ticker] = df
    spy_df = _load("SPY", days, profile.data_dir, fetch)
    graded = [grade_pick(p, histories.get(p["ticker"]), spy_df, rules) for p in pick_list]
    return graded, buy_threshold, pick_list


def summary_from_graded(graded, buy_threshold, n_picks, *, min_matured=30) -> dict:
    """Compact reality-check numbers from already-graded picks (pure). The daily briefing
    header calls this to confront the reader with the app's real hit-rate. Below
    `min_matured` matured picks the numbers are withheld (`enough=False`) — a young ledger
    is noise, and a misleading percentage at the decision moment is the whole thing to avoid.
    """
    fwd = summarize_scorecard(graded, "ret_5d", "alpha_5d", buy_threshold)
    sim = summarize_sim(graded)["summary"]
    cohort = fwd["cohort"] or fwd["overall"]   # actionable cohort, or all picks if no threshold
    alpha = cohort.get("avg_alpha")
    n_matured = fwd["n_matured"]
    return {
        "n_picks": n_picks,
        "n_matured": n_matured,
        "enough": n_matured >= min_matured,
        "cohort_alpha_5d": alpha,
        "beat_spy_rate": cohort.get("beat_spy_rate"),
        "sim_expectancy": sim["expectancy"],
        "sim_win": sim["win_rate"],
        "underperforming": (alpha is not None and alpha < 0),
    }


def briefing_summary(profile: Profile | None = None, *, fetch=None, min_matured=30):
    """Reality-check summary for the daily briefing header, or None when nothing is logged.
    Writes nothing and prints nothing (unlike run()); safe to call in main.run's hot path.
    """
    if profile is None:
        profile = Profile.for_repo()
    if fetch is None:
        fetch = data.fetch_history
    graded, buy_threshold, pick_list = _grade(profile, fetch)
    if not pick_list:
        return None
    return summary_from_graded(graded, buy_threshold, len(pick_list), min_matured=min_matured)


def run(profile: Profile | None = None, *, fetch=None) -> ScorecardResult:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if profile is None:
        profile = Profile.for_repo()
    profile.ensure_dirs()
    if fetch is None:
        fetch = data.fetch_history

    graded, buy_threshold, pick_list = _grade(profile, fetch)
    date_str = dt.date.today().isoformat()

    if not pick_list:
        text = (f"# Stock Advisor — Pick Scorecard ({date_str})\n\n"
                "_No picks logged yet. Run a briefing (or let the daily run log some) and "
                "check back._\n")
        return ScorecardResult(date=date_str, text=text,
                               html="<div>No picks logged yet.</div>")

    horizons = (("ret_1d", "alpha_1d"), ("ret_5d", "alpha_5d"), ("ret_21d", "alpha_21d"))
    forward = {ret_key: summarize_scorecard(graded, ret_key, alpha_key, buy_threshold)
               for ret_key, alpha_key in horizons}
    unique = _first_per_ticker(graded)
    forward_unique = {ret_key: summarize_scorecard(unique, ret_key, alpha_key, buy_threshold)
                      for ret_key, alpha_key in horizons}
    result = {"graded": graded, "forward": forward, "forward_unique": forward_unique,
              "n_unique": len(unique), "sim": summarize_sim(graded),
              "by_signal": summarize_by_signal(graded)}

    text = render_scorecard_report(result, date_str)
    html = render_scorecard_html(result, date_str)
    report_path = profile.reports_dir / f"scorecard-{date_str}.md"
    report_path.write_text(text, encoding="utf-8")
    print(text)
    return ScorecardResult(date=date_str, text=text, html=html, graded=graded,
                           summaries={"forward": forward, "forward_unique": forward_unique,
                                      "sim": result["sim"], "by_signal": result["by_signal"]},
                           report_path=report_path)


if __name__ == "__main__":
    # Default to the owner's repo profile (matching backtest.py); --user grades the
    # packaged per-user install's picks under %APPDATA%/StockAdvisor instead.
    if "--user" in sys.argv[1:]:
        from src import apppaths
        run(profile=Profile.for_base(apppaths.user_base_dir()))
    else:
        run()
