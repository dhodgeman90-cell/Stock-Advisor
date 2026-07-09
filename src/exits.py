# -*- coding: utf-8 -*-
import pandas as pd
from src import indicators


def _resolve(position, defaults, key):
    """Per-position override beats the default; None means 'use default'."""
    val = position.get(key)
    return defaults[key] if val is None else val


def evaluate_exit(df, position, rules) -> dict:
    """Deterministic exit signals for one holding. Pure function, no I/O.

    Signals are returned in fixed priority order:
    stop_loss -> take_profit -> trend_break_slow -> trend_break_fast -> momentum_fade.
    """
    defaults = rules["defaults"]
    close = df["Close"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    entry = float(position["entry_price"])
    if entry <= 0:
        raise ValueError(f"{position['ticker']}: entry_price must be positive")
    pct_from_entry = (price - entry) / entry * 100

    stop_pct = float(_resolve(position, defaults, "stop_loss_pct"))
    # Optional volatility-scaled stop: a flat 5% is too tight on a high-ATR name (whipsaw) and
    # arbitrary on a calm one. When atr_stop_mult > 0, scale by ATR but keep it bounded to
    # [0.5x, 2x] the flat stop so it never runs away. Off by default (mult 0) → flat stop.
    atr_mult = float(defaults.get("atr_stop_mult", 0) or 0)
    if atr_mult > 0:
        atr_val = float(indicators.atr(df, int(defaults.get("atr_period", 14))).iloc[-1])
        if not pd.isna(atr_val) and price > 0:
            atr_stop_pct = atr_mult * atr_val / price * 100
            stop_pct = min(max(atr_stop_pct, stop_pct * 0.5), stop_pct * 2.0)
    mode = str(defaults.get("take_profit_mode", "hard")).lower()
    # MA periods are global only — no per-position override
    fast = int(defaults["trend_break_fast"])
    slow = int(defaults["trend_break_slow"])
    fade = defaults["momentum_fade"]

    sma_fast = float(indicators.sma(close, fast).iloc[-1])
    sma_slow = float(indicators.sma(close, slow).iloc[-1])
    rsi_series = indicators.rsi(close, 14)  # RSI period is fixed (not currently a per-config knob)
    today_rsi = float(rsi_series.iloc[-1])
    recent_rsi_max = float(rsi_series.tail(5).max())
    vol_ratio = indicators.volume_ratio(volume, 20)

    signals = []

    if price <= entry * (1 - stop_pct / 100):
        signals.append({
            "type": "stop_loss", "level": "sell", "emoji": "🔴",
            "detail": f"down {pct_from_entry:.1f}% from entry (stop -{stop_pct:.0f}%)",
        })

    if mode == "trailing":
        peak = max(float(position.get("peak_price") or entry), price)
        trail_pct = float(_resolve(position, defaults, "trailing_stop_pct"))
        if peak > 0 and price <= peak * (1 - trail_pct / 100):
            signals.append({
                "type": "trailing_stop", "level": "sell", "emoji": "🔴",
                "detail": (f"down {(price - peak) / peak * 100:.1f}% from peak "
                           f"${peak:.2f} (trail -{trail_pct:.0f}%)"),
            })
    else:
        target_pct = float(_resolve(position, defaults, "take_profit_pct"))
        if price >= entry * (1 + target_pct / 100):
            signals.append({
                "type": "take_profit", "level": "trim", "emoji": "🟢",
                "detail": f"up {pct_from_entry:.1f}% from entry (target +{target_pct:.0f}%)",
            })

    slow_level = str(defaults.get("trend_break_slow_level", "sell")).lower()
    if not pd.isna(sma_slow) and price < sma_slow:
        signals.append({
            "type": "trend_break_slow", "level": slow_level,
            "emoji": "🔴" if slow_level == "sell" else "🟡",
            "detail": f"close ${price:.2f} below {slow}-day MA ${sma_slow:.2f}",
        })

    if not pd.isna(sma_fast) and price < sma_fast:
        signals.append({
            "type": "trend_break_fast", "level": "watch", "emoji": "🟡",
            "detail": f"close ${price:.2f} below {fast}-day MA ${sma_fast:.2f}",
        })

    if (not pd.isna(recent_rsi_max)
            and recent_rsi_max > float(fade["rsi_was_above"])
            and today_rsi < recent_rsi_max
            and vol_ratio < float(fade["volume_dry_ratio"])):
        signals.append({
            "type": "momentum_fade", "level": "watch", "emoji": "🟡",
            "detail": (f"RSI rolling over (peaked {recent_rsi_max:.0f}) "
                       f"on drying volume ({vol_ratio:.1f}x avg)"),
        })

    # Live time-stop: free capital from a position that's just drifting sideways (no price
    # signal fired) past `max_hold_days` CALENDAR days. Gated on entry_date, which live
    # holdings carry but the backtest's synthetic positions do not — so the backtest, which
    # owns its own bar-based max-hold force-close, is left byte-for-byte unchanged.
    last_ts = df.index[-1]
    max_hold = int(defaults.get("max_hold_days", 0) or 0)
    entry_date = position.get("entry_date")
    if max_hold > 0 and entry_date:
        held_days = (pd.Timestamp(last_ts) - pd.Timestamp(entry_date)).days
        if held_days >= max_hold:
            signals.append({
                "type": "time_exit", "level": "sell", "emoji": "🔴",
                "detail": f"held {held_days}d with no exit signal (max {max_hold}d) — freeing capital",
            })

    as_of = str(last_ts.date()) if hasattr(last_ts, "date") else str(last_ts)
    return {
        "ticker": position["ticker"],
        "current_price": price,
        "pct_from_entry": pct_from_entry,
        "signals": signals,
        "as_of": as_of,
    }
