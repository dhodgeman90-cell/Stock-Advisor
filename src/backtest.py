import datetime as dt
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from src import config, data, scoring, exits, adjudicator, edgar, objectives, regimes, market

ROOT = Path(__file__).resolve().parent.parent
MIN_HISTORY = 60   # 50 rows for the SMA-50 warm-up + ~10 days before the first decision
_EXIT_LEVELS = {"sell", "trim"}   # signal levels that close a backtest trade

# The ONLY adjudicator signals that can be honestly reconstructed point-in-time from free
# data for a historical backtest. Everything else — congress, insider, analyst, short
# interest, options flow, estimate revisions, WSB, and the AI news/risk/social agents — has
# no free as-of history (yfinance/.info are current snapshots, ApeWisdom has no archive), so
# it is EXCLUDED. Stamping today's values onto past bars would be look-ahead that fabricates
# alpha. Macro regime is reconstructable but deferred (only ±5). Coverage is reported so a
# partial backtest is never mistaken for validation of the full enriched engine.
_RECONSTRUCTABLE_CAPS = ("edgar_catalyst", "activist_stake", "risk_high")   # risk_high via 8-K severe

# Neutral views fed to the adjudicator for the un-reconstructable AI signals, so only the
# base score + point-in-time EDGAR actually move the enriched score.
_BT_NEUTRAL_NEWS = {"catalyst": False, "sentiment": "neutral", "summary": ""}
_BT_NEUTRAL_RISK = {"risk_level": "low", "veto": False, "reason": ""}
_BT_CONTEXT = {"regime": "neutral", "note": ""}


def _load_history(ticker, days, data_dir):
    """Return (df_or_None, source). Tries live fetch, falls back to cache.

    source is 'live', 'cache', or 'skipped'. Never raises on a bad fetch.
    """
    try:
        df = data.fetch_history(ticker, days)
    except Exception:
        df = None
    if df is not None and data.validate(df, ticker)[0]:
        data.save_cache(df, ticker, data_dir)
        return df, "live"
    cached = data.load_cache(ticker, data_dir)
    if cached is not None and data.validate(cached, ticker)[0]:
        return cached, "cache"
    return None, "skipped"


def _net_return(entry_price, exit_price, rules) -> float:
    """Trade return (%) after a round-trip transaction cost."""
    raw = (exit_price - entry_price) / entry_price * 100
    cost = 2 * float(rules["backtest"].get("cost_pct_per_side", 0.0))
    return raw - cost


def simulate_ticker(df, ticker, weights, settings, rules, *, score_of=None) -> list:
    """Trade-by-trade replay for one ticker. Returns a list of closed trades.

    Entry: when the decision score >= buy_threshold and no trade is open, buy at the
    NEXT day's open (no look-ahead). Exit: on a 'sell'-level signal or a
    take_profit, evaluated against that day's close; force-close at max_hold_days.
    One open trade per ticker at a time.

    `score_of(window, ticker, base_res) -> float` overrides the entry score. Default
    (None) uses the base technical score — the original behaviour, byte-for-byte. The
    enriched backtest passes a reconstructor that runs the real adjudicator per bar.
    """
    bt = rules["backtest"]
    threshold = float(bt["buy_threshold"])
    max_hold = int(bt["max_hold_days"])

    trades = []
    open_trade = None
    n = len(df)
    i = MIN_HISTORY
    while i < n:
        window = df.iloc[: i + 1]
        if open_trade is None:
            res = scoring.score_ticker(window, ticker, weights, settings)
            if not res.get("excluded"):
                entry_score = res["score"] if score_of is None else score_of(window, ticker, res)
            else:
                entry_score = None      # liquidity/price floor failed — never enter
            if entry_score is not None and entry_score >= threshold and (i + 1) < n:
                entry_idx = i + 1
                open_trade = {
                    "entry_idx": entry_idx,
                    "entry_price": float(df["Open"].iloc[entry_idx]),
                    "entry_date": df.index[entry_idx],
                    "peak": float(df["Open"].iloc[entry_idx]),
                }
                i = entry_idx           # resume exit checks the day AFTER entry
        else:
            open_trade["peak"] = max(open_trade["peak"], float(df["Close"].iloc[i]))
            position = {"ticker": ticker, "entry_price": open_trade["entry_price"],
                        "peak_price": open_trade["peak"]}
            ev = exits.evaluate_exit(window, position, rules)
            held_days = i - open_trade["entry_idx"]
            # Signals at _EXIT_LEVELS close the trade; 'watch'-level signals don't.
            # exits.py emits signals in priority order, so signals[0] is the trigger.
            signalled = any(s["level"] in _EXIT_LEVELS for s in ev["signals"])
            force = held_days >= max_hold
            if signalled or force:
                exit_price = float(df["Close"].iloc[i])
                reason = (next(s["type"] for s in ev["signals"] if s["level"] in _EXIT_LEVELS)
                          if signalled else "max_hold")
                ret = _net_return(open_trade["entry_price"], exit_price, rules)
                trades.append({
                    "ticker": ticker,
                    "entry_date": str(open_trade["entry_date"].date()),
                    "entry_price": open_trade["entry_price"],
                    "exit_date": str(df.index[i].date()),
                    "exit_price": exit_price,
                    "return_pct": ret,
                    "hold_days": held_days,
                    "reason": reason,
                })
                open_trade = None
        i += 1
    # Force-close any trade still open when the data window ends.
    if open_trade is not None:
        exit_price = float(df["Close"].iloc[-1])
        held_days = (n - 1) - open_trade["entry_idx"]
        ret = _net_return(open_trade["entry_price"], exit_price, rules)
        trades.append({
            "ticker": ticker,
            "entry_date": str(open_trade["entry_date"].date()),
            "entry_price": open_trade["entry_price"],
            "exit_date": str(df.index[-1].date()),
            "exit_price": exit_price,
            "return_pct": ret,
            "hold_days": held_days,
            "reason": "end_of_data",
        })
    return trades


def summarize(trades) -> dict:
    if not trades:
        return {"count": 0, "win_rate": 0.0, "avg_gain": 0.0, "avg_loss": 0.0,
                "avg_hold": 0.0, "total_return": 0.0, "avg_trade_return": 0.0,
                "expectancy": 0.0, "by_reason": Counter()}
    rets = [t["return_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]   # break-even (0%) counts as a loss (conservative)
    avg_gain = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    return {
        "count": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_gain": avg_gain,
        "avg_loss": avg_loss,
        "avg_hold": sum(t["hold_days"] for t in trades) / len(trades),
        "total_return": sum(rets),
        "avg_trade_return": sum(rets) / len(trades),
        "expectancy": (len(wins) / len(trades)) * avg_gain
                      + (len(losses) / len(trades)) * avg_loss,
        "by_reason": Counter(t["reason"] for t in trades),
    }


def compounded_per_name(trades) -> float:
    """Per-ticker sequential trades compound; average the result across tickers (%).

    Comparable to per-name buy-and-hold because each ticker holds one trade at a time.
    """
    factors = {}
    for t in trades:
        factors[t["ticker"]] = factors.get(t["ticker"], 1.0) * (1 + t["return_pct"] / 100)
    if not factors:
        return 0.0
    rets = [(f - 1) * 100 for f in factors.values()]
    return sum(rets) / len(rets)


def max_drawdown(values) -> float:
    """Worst peak-to-trough drop of an equity series, as a negative percent.

    0.0 if the series never falls below a running peak (or is empty).
    """
    peak = None
    worst = 0.0
    for v in values:
        v = float(v)
        if peak is None or v > peak:
            peak = v
        if peak:
            dd = (v - peak) / peak * 100
            if dd < worst:
                worst = dd
    return worst


def buy_and_hold(histories) -> float:
    """Equal-weight buy-and-hold return (%) across the watchlist over the window."""
    rets = []
    for df in histories.values():
        first = float(df["Close"].iloc[0])
        last = float(df["Close"].iloc[-1])
        if first:
            rets.append((last - first) / first * 100)
    return (sum(rets) / len(rets)) if rets else 0.0


def _portfolio_curve(slices) -> list:
    """Equal-weight mean of normalized per-ticker slice Series.

    Aligns on the union of their dates and forward-fills, so a name with a
    shorter history contributes only once it has data (leading gaps are NaN and
    excluded from the mean). Returns the daily portfolio values.
    """
    if not slices:
        return []
    frame = pd.concat(slices, axis=1).sort_index().ffill()
    return [float(v) for v in frame.mean(axis=1, skipna=True).tolist()]


def _strategy_slice(df, ticker_trades):
    """Normalized account value for one ticker over its history (starts at 1.0).

    Flat while in cash; tracks close/entry_price while holding; locks in the
    realized (cost-inclusive) factor on the trade's exit date, then flat again.
    """
    by_entry = {t["entry_date"]: t for t in ticker_trades}
    factor = 1.0
    entry_price = None
    open_trade = None
    out = []
    for ts, close in zip(df.index, df["Close"]):
        d = str(ts.date())
        if open_trade is None and d in by_entry:
            open_trade = by_entry[d]
            entry_price = open_trade["entry_price"]
        if open_trade is not None:
            if d == open_trade["exit_date"]:
                factor = factor * (1 + open_trade["return_pct"] / 100)
                out.append(factor)
                open_trade = None
                entry_price = None
            else:
                out.append(factor * (float(close) / entry_price))
        else:
            out.append(factor)
    return pd.Series(out, index=df.index)


def strategy_equity_curve(histories, trades) -> list:
    """Equal-weight daily portfolio curve for the strategy (cash between trades)."""
    by_ticker = {}
    for t in trades:
        by_ticker.setdefault(t["ticker"], []).append(t)
    slices = [_strategy_slice(df, by_ticker.get(ticker, []))
              for ticker, df in histories.items()]
    return _portfolio_curve(slices)


def buy_and_hold_equity_curve(histories) -> list:
    """Equal-weight daily portfolio curve for always-invested buy-and-hold."""
    slices = []
    for df in histories.values():
        first = float(df["Close"].iloc[0])
        if first:
            slices.append(df["Close"].astype(float) / first)
    return _portfolio_curve(slices)


def render_backtest_report(summary, baseline, trades, date_str, label="default",
                           sources=None, strategy_dd=0.0, buyhold_dd=0.0) -> str:
    compounded = compounded_per_name(trades)
    L = [
        f"# Stock Advisor — Backtest ({label}, {date_str})",
        "",
        f"- Trades: **{summary['count']}**",
        f"- Win rate: **{summary['win_rate']:.0f}%**",
        f"- Avg gain: **{summary['avg_gain']:+.1f}%**  |  Avg loss: **{summary['avg_loss']:+.1f}%**",
        f"- Expectancy per trade: **{summary['expectancy']:+.1f}%**",
        f"- Avg hold: **{summary['avg_hold']:.0f}** trading days",
        "",
        "### Strategy vs buy-and-hold (per name, comparable)",
        f"- Strategy return per name (compounded): **{compounded:+.1f}%**",
        f"- Buy-and-hold baseline (avg per watchlist name): **{baseline:+.1f}%**",
        f"- Avg return per trade: **{summary['avg_trade_return']:+.1f}%**",
        f"- Strategy max drawdown: **{strategy_dd:+.1f}%**",
        f"- Buy-and-hold max drawdown: **{buyhold_dd:+.1f}%**",
        "",
        "## Exit reasons",
    ]
    if summary["by_reason"]:
        for reason, count in summary["by_reason"].most_common():
            L.append(f"- {reason.replace('_', ' ')}: {count}")
    else:
        L.append("_No trades._")
    if sources:
        tally = Counter(sources.values())
        L.append("")
        L.append("## Data sources")
        for src, n in tally.most_common():
            L.append(f"- {src}: {n} tickers")
    L.append("")
    L.append("## Trades")
    if trades:
        for t in trades:
            L.append(
                f"- {t['ticker']} {t['entry_date']} → {t['exit_date']} "
                f"({t['hold_days']}d): {t['return_pct']:+.1f}% "
                f"[{t['reason'].replace('_', ' ')}]"
            )
    else:
        L.append("_No trades._")
    L.append("")
    L.append("> Caveat: a good backtest is encouraging, not a guarantee. Overfitting is a "
             "real risk — treat these numbers skeptically and confirm with paper trading.")
    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"


def run(watchlist_name=None) -> str:
    wl = config.load_watchlist(name=watchlist_name)
    weights = config.load_weights()
    rules = config.load_exit_rules()
    settings = wl["settings"]
    years = int(rules["backtest"]["window_years"])
    days = years * 365
    data_dir = ROOT / "data"

    histories = {}
    all_trades = []
    sources = {}
    for ticker in wl["tickers"]:
        df, source = _load_history(ticker, days, data_dir)
        sources[ticker] = source
        if df is None:
            continue
        histories[ticker] = df
        all_trades.extend(simulate_ticker(df, ticker, weights, settings, rules))

    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    strategy_dd = max_drawdown(strategy_equity_curve(histories, all_trades))
    buyhold_dd = max_drawdown(buy_and_hold_equity_curve(histories))
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str,
                                  label=label, sources=sources,
                                  strategy_dd=strategy_dd, buyhold_dd=buyhold_dd)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-{label}-{date_str}.md").write_text(text, encoding="utf-8")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


# ===================== Enriched backtest (P0-a) =============================
# Replays the ADJUDICATED final_score (base technicals + point-in-time SEC EDGAR), not just
# the base score, so we can ask the real question: does the engine we actually trade beat
# buy-and-hold on history — after costs AND the short-term-gains tax that buy-and-hold
# avoids? It can only reconstruct the free, point-in-time signals; coverage is reported so a
# partial result is never mistaken for validation of the full engine.

def apply_tax(trades, tax_pct) -> list:
    """Apply a flat short-term-gains haircut to WINNING trades (losses unchanged). This is
    the tax drag active trading pays and buy-and-hold does not — the hurdle an edge must clear."""
    if not tax_pct:
        return list(trades)
    out = []
    for t in trades:
        r = t["return_pct"]
        out.append({**t, "return_pct": r * (1 - tax_pct / 100.0) if r > 0 else r})
    return out


def _cap_coverage(caps) -> float:
    """Rough % of the adjudicator cap budget the enriched backtest can reconstruct."""
    total = sum(abs(float(v)) for v in caps.values())
    covered = sum(abs(float(caps.get(k, 0))) for k in _RECONSTRUCTABLE_CAPS)
    return (100.0 * covered / total) if total else 0.0


def _edgar_enricher(recent, caps, thresholds, sec_window):
    """Return score_of(window, ticker, base_res) that reconstructs the enriched final_score
    from base technicals + point-in-time EDGAR only. `recent` = the ticker's SEC
    filings.recent arrays (fetched once). Un-reconstructable signals are fed neutral/None."""
    forms = (recent or {}).get("form", [])
    items = (recent or {}).get("items", [])
    dates = (recent or {}).get("filingDate", [])

    def score_of(window, ticker, res):
        bar_date = window.index[-1].date()
        sig = edgar.signal_asof(forms, items, dates, bar_date, window_days=sec_window)
        # Look-ahead is a BUILD failure, not a silent bug: no reconstructed filing may
        # postdate the bar we decide on. signal_asof guarantees this; the assert makes any
        # future regression fail loudly instead of quietly manufacturing alpha.
        assert sig["as_of"] is None or sig["as_of"] <= bar_date.isoformat(), \
            f"look-ahead: EDGAR as_of {sig['as_of']} > bar {bar_date}"
        adjd = adjudicator.adjudicate(
            {"ticker": ticker, "score": res["score"]},
            dict(_BT_NEUTRAL_NEWS), dict(_BT_NEUTRAL_RISK), dict(_BT_CONTEXT), caps,
            thresholds=thresholds, edgar=sig,
        )
        return adjd["final_score"]
    return score_of


def enriched_backtest_core(histories, recent_by_ticker, base_weights, base_rules, settings,
                           caps, thresholds, *, presets=None, sec_window=30) -> dict:
    """Pure (no network): replay the enriched engine over `histories` for each objective
    preset, alongside the base-score engine, both cost- and STCG-tax-adjusted, vs an
    equal-weight buy-and-hold baseline. `recent_by_ticker` maps ticker -> SEC filings.recent
    arrays (or {}). Returns a structured result for render_enriched_report."""
    presets = presets or objectives.ORDER
    baseline = buy_and_hold(histories)
    buyhold_dd = max_drawdown(buy_and_hold_equity_curve(histories))

    per_preset = {}
    for key in presets:
        weights_p = objectives.apply_weights(base_weights, key)
        rules_p = objectives.apply_exit_rules(base_rules, key)
        tax = float(rules_p["backtest"].get("stcg_tax_pct", 0))
        enr_trades, base_trades = [], []
        for ticker, df in histories.items():
            enricher = _edgar_enricher(recent_by_ticker.get(ticker, {}), caps, thresholds, sec_window)
            enr_trades += apply_tax(
                simulate_ticker(df, ticker, weights_p, settings, rules_p, score_of=enricher), tax)
            base_trades += apply_tax(
                simulate_ticker(df, ticker, weights_p, settings, rules_p), tax)
        per_preset[key] = {
            "label": objectives.get(key)["label"],
            "tax_pct": tax,
            "enriched": {"summary": summarize(enr_trades),
                         "compounded": compounded_per_name(enr_trades),
                         "dd": max_drawdown(strategy_equity_curve(histories, enr_trades))},
            "base": {"summary": summarize(base_trades),
                     "compounded": compounded_per_name(base_trades)},
        }
    best = max((p["enriched"]["compounded"] for p in per_preset.values()), default=0.0)
    return {
        "per_preset": per_preset, "baseline": baseline, "buyhold_dd": buyhold_dd,
        "coverage_pct": _cap_coverage(caps), "n_names": len(histories),
        "best_enriched": best, "beat_buyhold": best > baseline,
    }


def per_regime_summary(histories, recent_by_ticker, base_weights, base_rules, settings,
                       caps, thresholds, *, presets=None, sec_window=30) -> dict:
    """Run the enriched backtest on each regime sub-window (2022 selloff, 2023-24 bull,
    2025-26, full cycle). Returns {regime_name: core}. A window with too little in-range
    history to trade is skipped, so a strategy is judged on the down/flat regimes — not
    just the bull run that flatters it. Pure (no network); reuses enriched_backtest_core."""
    out = {}
    for name, (start, end) in regimes.SUBPERIODS.items():
        sliced = regimes.slice_histories(histories, start, end)
        if not sliced:
            continue
        out[name] = enriched_backtest_core(
            sliced, recent_by_ticker, base_weights, base_rules, settings,
            caps, thresholds, presets=presets, sec_window=sec_window)
    return out


def _best_preset(core):
    """(label, compounded, dd) of the highest-compounded enriched preset in a core."""
    best = None
    for p in core["per_preset"].values():
        c = p["enriched"]["compounded"]
        if best is None or c > best[1]:
            best = (p["label"], c, p["enriched"]["dd"])
    return best or ("—", 0.0, 0.0)


def _ret_per_dd(ret, dd) -> float:
    """Return per unit of drawdown (Calmar-style). 0 drawdown -> 0.0 to stay finite."""
    return ret / abs(dd) if dd else 0.0


def render_enriched_report(core, date_str, label="default", *, years=None, date_range=None,
                           per_regime=None) -> str:
    win = f"{date_range[0]} → {date_range[1]}" if date_range else f"~{years}y"
    tax_pct = next((p["tax_pct"] for p in core["per_preset"].values()), 0)
    L = [
        f"# Stock Advisor — Enriched Backtest ({label}, {date_str})", "",
        f"Window: **{win}** · names: **{core['n_names']}**", "",
        "> **Partial engine — read this first.** This replays the base technical score PLUS "
        "the only signals honestly reconstructable point-in-time on free data: SEC EDGAR "
        f"8-K / 13D (real filing dates). Estimated cap-budget coverage: **~{core['coverage_pct']:.0f}%**. "
        "EXCLUDED (no free as-of history): congress, insider, analyst, short interest, options "
        "flow, estimate revisions, WSB, and the AI news/risk/social agents; macro regime is "
        "deferred. So this is NOT validation of the full enriched engine — only of the part we "
        "can test honestly against history.", "",
        "### Strategy vs buy-and-hold, per objective preset (after cost + short-term tax)",
        f"Equal-weight buy-and-hold baseline (untaxed): **{core['baseline']:+.1f}%** per name "
        f"· max drawdown **{core['buyhold_dd']:+.1f}%**", "",
        "| Preset | Enriched | Base | vs B&H | Win% | Expectancy | Trades | MaxDD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key in objectives.ORDER:
        p = core["per_preset"].get(key)
        if not p:
            continue
        e, b, s = p["enriched"], p["base"], p["enriched"]["summary"]
        L.append(f"| {p['label']} | {e['compounded']:+.1f}% | {b['compounded']:+.1f}% | "
                 f"{e['compounded'] - core['baseline']:+.1f}% | {s['win_rate']:.0f}% | "
                 f"{s['expectancy']:+.1f}% | {s['count']} | {e['dd']:+.1f}% |")
    L += ["", f"_Short-term-gains haircut on winning trades: {tax_pct:.0f}% "
              "(buy-and-hold pays none — that's the hurdle daily trading must clear)._", ""]

    if core["beat_buyhold"]:
        L += ["## Verdict — a measured edge (partial)",
              f"The best preset's enriched, after-cost/after-tax return "
              f"(**{core['best_enriched']:+.1f}%**) beat equal-weight buy-and-hold "
              f"(**{core['baseline']:+.1f}%**) over this window — on the reconstructable subset "
              "ONLY (~coverage above). That clears the P0-a gate to *consider* P1 work, but "
              "treat it cautiously: partial coverage, one window, is not proof."]
    else:
        L += ["## Verdict — NO measured edge",
              f"No preset's enriched, after-cost/after-tax return beat equal-weight "
              f"buy-and-hold (**{core['baseline']:+.1f}%**) over this window "
              f"(best was **{core['best_enriched']:+.1f}%**). Per the plan's kill criterion, "
              "daily-trading these names shows **no measured edge here — do not start P1 "
              "feature work on this evidence.** Grow the ledger (P0-b) and re-check across "
              "more regimes first."]
    if per_regime:
        L += ["", "### Per-regime — best preset vs buy-and-hold",
              "A timing strategy can only beat buy-and-hold over a full cycle by LOSING LESS "
              "in the down/flat regimes. This splits the same run by market regime so that "
              "edge (or its absence) is visible, not averaged away by the bull run.", "",
              "| Regime | Best preset | Return | MaxDD | Return/DD | B&H return | B&H MaxDD |",
              "|---|---|---|---|---|---|---|"]
        for name, rc in per_regime.items():
            plabel, ret, dd = _best_preset(rc)
            L.append(f"| {name.replace('_', ' ')} | {plabel} | {ret:+.1f}% | {dd:+.1f}% | "
                     f"{_ret_per_dd(ret, dd):.2f} | {rc['baseline']:+.1f}% | "
                     f"{rc['buyhold_dd']:+.1f}% |")
    L += ["",
          "> Caveat: partial-engine, single-window, free-data backtest. Overfitting and "
          "survivorship risk remain — confirm against the live scorecard as the ledger grows.",
          "", "_Information only — not financial advice._"]
    return "\n".join(L) + "\n"


def run_enriched(watchlist_name=None, *, years=None) -> str:
    wl = config.load_watchlist(name=watchlist_name)
    base_weights = config.load_weights()
    base_rules = config.load_exit_rules()
    caps = config.load_adjudicator()
    thresholds = config.load_signals()["thresholds"]
    settings = wl["settings"]
    sec_window = thresholds.get("sec_window_days", edgar.DEFAULT_WINDOW_DAYS)
    years = int(years or base_rules["backtest"].get("enriched_years", 4))
    data_dir = ROOT / "data"

    histories, sources = {}, {}
    for ticker in wl["tickers"]:
        df, source = _load_history(ticker, years * 365, data_dir)
        sources[ticker] = source
        if df is not None:
            histories[ticker] = df

    # SEC filings per ticker (fetched once each; degrade to empty -> neutral EDGAR on failure).
    cik_map = edgar.load_cik_map()
    recent_by_ticker = {}
    for ticker in histories:
        try:
            cik = cik_map.get(ticker.upper())
            recent_by_ticker[ticker] = (
                edgar._default_submissions_fetch(cik).get("filings", {}).get("recent", {})
                if cik else {})
        except Exception:
            recent_by_ticker[ticker] = {}

    core = enriched_backtest_core(histories, recent_by_ticker, base_weights, base_rules,
                                  settings, caps, thresholds, sec_window=sec_window)
    # Per-regime breakdown so the strategy is judged on the 2022 selloff + flat stretches,
    # not just the bull run. Backtest-only; no effect on the live briefing.
    per_regime = per_regime_summary(histories, recent_by_ticker, base_weights, base_rules,
                                    settings, caps, thresholds, sec_window=sec_window)
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    date_range = None
    if histories:
        starts = [df.index[0] for df in histories.values()]
        ends = [df.index[-1] for df in histories.values()]
        date_range = (str(min(starts).date()), str(max(ends).date()))
    text = render_enriched_report(core, date_str, label=label, years=years,
                                  date_range=date_range, per_regime=per_regime)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-enriched-{label}-{date_str}.md").write_text(text, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


# ===================== Portfolio simulator + regime overlay (Phase 2) ======
# simulate_ticker is per-ticker/one-trade and can't express "hold the top-N today" or a
# cash sleeve. This is a NEW cross-sectional loop: each bar, rank the eligible names, hold
# the top-N equal-weight scaled by a regime exposure gate, the rest in cash. Daily rebalanced
# — rotation IS the exit (a name that weakens drops out of the top-N).
# ponytail: per-position stop/trail exits are omitted here — the daily re-rank already ejects
# breakdowns. Add exits.evaluate_exit into the loop only if validation shows the rotation
# misses fast intra-name crashes. Execution is close-to-close (decide at bar i's close, realize
# i -> i+1) — a standard look-ahead-free convention.

DEFAULT_EXPOSURE_MAP = {"risk_on": 1.0, "neutral": 1.0, "risk_off": 0.3}


def simulate_portfolio(histories, rank_of, rules, *, top_n=8, regime=None,
                       exposure_map=None, start_i=None) -> dict:
    """Daily-rebalanced equal-weight top-N portfolio with a regime exposure gate + cash.

    Each bar i: rank every eligible name via rank_of(bar_date, ticker, window<=i), hold the
    top_n at equal weight scaled by exposure E=exposure_map[regime[i]] (default 1.0), the rest
    in cash (0% return). rank_of returning None = ineligible (e.g. the liquidity/price gate).
    Realizes the book's i->i+1 return; turnover is charged cost_pct_per_side on each side.
    Returns {equity_curve, total_return, exposure_avg, turnover_avg}. Look-ahead free: the
    decision at bar i uses only bars <= i (asserted); the return is realized on the next bar."""
    start_i = MIN_HISTORY if start_i is None else start_i
    closes = pd.DataFrame({tk: df["Close"].astype(float)
                           for tk, df in histories.items()}).sort_index()
    dates = closes.index
    n = len(dates)
    cost = float(rules["backtest"].get("cost_pct_per_side", 0.0)) / 100.0

    equity = 1.0
    curve = [equity]
    prev_w = {}
    exposures, turnovers = [], []
    for i in range(start_i, n - 1):
        date = dates[i]
        ranked = []
        for tk in histories:
            c = closes.at[date, tk]
            if pd.isna(c):
                continue
            window = histories[tk].loc[:date]
            assert window.index[-1] <= date, "look-ahead: rank window extends past the bar"
            r = rank_of(date, tk, window)
            if r is not None:
                ranked.append((r, tk))
        ranked.sort(key=lambda rt: rt[0], reverse=True)
        selected = [tk for _, tk in ranked[:top_n]]

        E = 1.0
        if regime is not None and exposure_map is not None:
            E = exposure_map.get(regime.get(date, "risk_on"), 1.0)
        exposures.append(E)

        w = (E / len(selected)) if selected else 0.0
        weights = {tk: w for tk in selected}
        names = set(weights) | set(prev_w)
        turnover = sum(abs(weights.get(tk, 0.0) - prev_w.get(tk, 0.0)) for tk in names)
        turnovers.append(turnover)

        nxt = dates[i + 1]
        port_ret = 0.0
        for tk in selected:
            c0, c1 = closes.at[date, tk], closes.at[nxt, tk]
            if pd.notna(c0) and pd.notna(c1) and c0:
                port_ret += weights[tk] * (c1 / c0 - 1.0)
        equity *= (1 + port_ret - turnover * cost)
        curve.append(equity)
        prev_w = weights

    return {
        "equity_curve": curve,
        "total_return": (equity - 1) * 100.0,
        "exposure_avg": (sum(exposures) / len(exposures)) if exposures else 0.0,
        "turnover_avg": (sum(turnovers) / len(turnovers)) if turnovers else 0.0,
    }


def _portfolio_metrics(sim, tax_pct) -> dict:
    """Metrics for a simulate_portfolio result. Return is after the STCG haircut (the hurdle
    an active strategy pays and B&H doesn't); drawdown is the PRE-tax path (tax changes the
    endpoint, not the intra-path shape)."""
    pre = sim["total_return"]
    after = pre * (1 - tax_pct / 100.0) if pre > 0 else pre
    dd = max_drawdown(sim["equity_curve"])
    return {"return": after, "return_pretax": pre, "dd": dd, "calmar": _ret_per_dd(after, dd),
            "exposure_avg": sim["exposure_avg"], "turnover_avg": sim["turnover_avg"]}


def _kill_criterion(per_regime) -> dict:
    """The gate: a timing overlay earns live deployment only if it loses less in the downturn
    without bleeding the recovery. All present checks must pass. (return/|DD| = Calmar-style.)"""
    checks = {}
    full = per_regime.get("full")
    if full:
        checks["c1_full_calmar_ge_bh"] = full["on"]["calmar"] >= full["bh"]["calmar"]
    sell = per_regime.get("2022_selloff")
    if sell:
        checks["c2_selloff_on_beats_bh"] = sell["on"]["return"] > sell["bh"]["return"]
    bull = per_regime.get("2023_24_bull")
    if bull:
        off_r = bull["off"]["return"]
        checks["c3_bull_not_bled"] = bull["on"]["return"] >= off_r - 0.1 * abs(off_r)
    subs = [per_regime[k] for k in ("2022_selloff", "2023_24_bull", "2025_26") if k in per_regime]
    if subs:
        wins = sum(1 for s in subs if s["on"]["calmar"] > s["off"]["calmar"])
        checks["c4_on_beats_off_calmar_2of3"] = wins >= 2
    return {"checks": checks, "passed": bool(checks) and all(checks.values())}


def validate_regime_overlay(histories, spy_df, rank_of, rules, *, top_n=8, exposure_map=None,
                            tax_pct=0.0, confirm_down=3, confirm_up=5, start_i=None) -> dict:
    """Run overlay-OFF vs overlay-ON vs buy-and-hold across each regime sub-window + full cycle.
    The overlay uses the point-in-time SPY regime (Phase 1), hysteresis-smoothed. Returns a
    structured result (per-regime metrics + the kill-criterion verdict) for render_regime_report."""
    exposure_map = exposure_map or DEFAULT_EXPOSURE_MAP
    regime = market.apply_hysteresis(
        market.regime_series(spy_df), confirm_down=confirm_down, confirm_up=confirm_up)
    per_regime = {}
    for name, (start, end) in regimes.SUBPERIODS.items():
        sliced = regimes.slice_histories(histories, start, end)
        if not sliced:
            continue
        reg_slice = regime.loc[start:end]
        off = simulate_portfolio(sliced, rank_of, rules, top_n=top_n, start_i=start_i)
        on = simulate_portfolio(sliced, rank_of, rules, top_n=top_n, start_i=start_i,
                                regime=reg_slice, exposure_map=exposure_map)
        bh_ret = buy_and_hold(sliced)
        bh_dd = max_drawdown(buy_and_hold_equity_curve(sliced))
        per_regime[name] = {
            "off": _portfolio_metrics(off, tax_pct),
            "on": _portfolio_metrics(on, tax_pct),
            "bh": {"return": bh_ret, "dd": bh_dd, "calmar": _ret_per_dd(bh_ret, bh_dd)},
        }
    return {"per_regime": per_regime, "verdict": _kill_criterion(per_regime),
            "exposure_map": exposure_map, "n_names": len(histories)}


_CRITERION_LABELS = {
    "c1_full_calmar_ge_bh": "1. Full-cycle return/|DD| ≥ buy-and-hold",
    "c2_selloff_on_beats_bh": "2. 2022 selloff: overlay-ON return beats buy-and-hold",
    "c3_bull_not_bled": "3. 2023-24 bull: overlay-ON ≥ 90% of overlay-OFF (recovery not bled)",
    "c4_on_beats_off_calmar_2of3": "4. Overlay-ON return/|DD| beats OFF in ≥2 of 3 sub-periods",
}


def render_regime_report(result, date_str, label="default") -> str:
    pr, v, em = result["per_regime"], result["verdict"], result["exposure_map"]
    L = [
        f"# Stock Advisor — Regime Overlay Validation ({label}, {date_str})", "",
        f"Names: **{result['n_names']}** · defensive exposure: risk_off → "
        f"**{em.get('risk_off', 1.0):.0%}** invested (else 100%). Overlay-ON scales market "
        "exposure down only in *confirmed* downtrends; OFF is always fully invested; B&H holds.",
        "",
        "| Regime | Cfg | Return | MaxDD | Return/DD | AvgExp | Turnover |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in regimes.SUBPERIODS:
        if name not in pr:
            continue
        disp = name.replace("_", " ")
        for cfg in ("off", "on"):
            m = pr[name][cfg]
            L.append(f"| {disp} | {cfg.upper()} | {m['return']:+.1f}% | {m['dd']:+.1f}% | "
                     f"{m['calmar']:.2f} | {m['exposure_avg']:.0%} | {m['turnover_avg']:.2f} |")
        b = pr[name]["bh"]
        L.append(f"| {disp} | B&H | {b['return']:+.1f}% | {b['dd']:+.1f}% | {b['calmar']:.2f} | 100% | — |")
    L += ["", "### Kill criterion (walk-forward gate)", ""]
    for key, txt in _CRITERION_LABELS.items():
        if key in v["checks"]:
            L.append(f"- {'✅ PASS' if v['checks'][key] else '❌ FAIL'} — {txt}")
    verdict = ("SHIP IT — overlay clears the gate" if v["passed"]
               else "DO NOT SHIP — overlay fails the kill criterion")
    L += ["", f"## Verdict — {verdict}", "",
          "> Walk-forward reminder: tune the exposure map / hysteresis on 2022-24 only, confirm "
          "on 2025-26. A regime timer can whipsaw in a V-shaped recovery; a partial, single-history "
          "backtest is evidence, not proof.", "", "_Information only — not financial advice._"]
    return "\n".join(L) + "\n"


def _base_rank_of(weights, settings):
    """rank_of over the real base technical score (reuses scoring.score_ticker's liquidity/price
    gate — an excluded name returns None)."""
    def rank_of(date, ticker, window):
        res = scoring.score_ticker(window, ticker, weights, settings)
        return None if res.get("excluded") else res["score"]
    return rank_of


def run_regime_validation(watchlist_name=None, *, years=6) -> str:
    """CLI: validate the regime exposure overlay on real history (default 6y to span 2020-ish
    onward). Writes reports/backtest-regime-<label>-<date>.md."""
    wl = config.load_watchlist(name=watchlist_name)
    weights = config.load_weights()
    rules = config.load_exit_rules()
    settings = wl["settings"]
    tax = float(rules["backtest"].get("stcg_tax_pct", 0))
    data_dir = ROOT / "data"

    histories = {}
    for ticker in wl["tickers"]:
        df, _ = _load_history(ticker, years * 365, data_dir)
        if df is not None:
            histories[ticker] = df
    spy_df, _ = _load_history("SPY", years * 365, data_dir)
    if spy_df is None:
        raise SystemExit("regime validation needs SPY history (fetch failed)")

    result = validate_regime_overlay(histories, spy_df, _base_rank_of(weights, settings),
                                     rules, tax_pct=tax)
    label = watchlist_name or "default"
    date_str = dt.date.today().isoformat()
    text = render_regime_report(result, date_str, label=label)
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-regime-{label}-{date_str}.md").write_text(text, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


if __name__ == "__main__":
    _args = sys.argv[1:]
    if "--regime" in _args:
        _rest = [a for a in _args if a != "--regime"]
        run_regime_validation(_rest[0] if _rest else None)
    elif "--enriched" in _args:
        _rest = [a for a in _args if a != "--enriched"]
        run_enriched(_rest[0] if _rest else None)
    else:
        run(_args[0] if _args else None)
