import datetime as dt
import sys
from collections import Counter
from pathlib import Path

from src import config, data, scoring, exits

ROOT = Path(__file__).resolve().parent.parent
MIN_HISTORY = 60   # 50 rows for the SMA-50 warm-up + ~10 days before the first decision
_EXIT_LEVELS = {"sell", "trim"}   # signal levels that close a backtest trade


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


def simulate_ticker(df, ticker, weights, settings, rules) -> list:
    """Trade-by-trade replay for one ticker. Returns a list of closed trades.

    Entry: when base score >= buy_threshold and no trade is open, buy at the
    NEXT day's open (no look-ahead). Exit: on a 'sell'-level signal or a
    take_profit, evaluated against that day's close; force-close at max_hold_days.
    One open trade per ticker at a time.
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
            if (not res.get("excluded")) and res["score"] >= threshold and (i + 1) < n:
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


def buy_and_hold(histories) -> float:
    """Equal-weight buy-and-hold return (%) across the watchlist over the window."""
    rets = []
    for df in histories.values():
        first = float(df["Close"].iloc[0])
        last = float(df["Close"].iloc[-1])
        if first:
            rets.append((last - first) / first * 100)
    return (sum(rets) / len(rets)) if rets else 0.0


def render_backtest_report(summary, baseline, trades, date_str, label="default", sources=None) -> str:
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


def run() -> str:
    wl = config.load_watchlist()
    weights = config.load_weights()
    rules = config.load_exit_rules()
    settings = wl["settings"]
    years = int(rules["backtest"]["window_years"])
    days = years * 365

    histories = {}
    all_trades = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, days)
        ok, _ = data.validate(df, ticker)
        if not ok:
            continue
        histories[ticker] = df
        all_trades.extend(simulate_ticker(df, ticker, weights, settings, rules))

    summary = summarize(all_trades)
    baseline = buy_and_hold(histories)
    date_str = dt.date.today().isoformat()
    text = render_backtest_report(summary, baseline, all_trades, date_str)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"backtest-{date_str}.md").write_text(text, encoding="utf-8")

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(text)
    return text


if __name__ == "__main__":
    run()
