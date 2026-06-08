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
    pct_from_entry = ((price - entry) / entry * 100) if entry else 0.0

    stop_pct = float(_resolve(position, defaults, "stop_loss_pct"))
    target_pct = float(_resolve(position, defaults, "take_profit_pct"))
    fast = int(defaults["trend_break_fast"])
    slow = int(defaults["trend_break_slow"])
    fade = defaults["momentum_fade"]

    sma_fast = float(indicators.sma(close, fast).iloc[-1])
    sma_slow = float(indicators.sma(close, slow).iloc[-1])
    rsi_series = indicators.rsi(close, 14)
    today_rsi = float(rsi_series.iloc[-1])
    recent_rsi_max = float(rsi_series.tail(5).max())
    vol_ratio = indicators.volume_ratio(volume, 20)

    signals = []

    if price <= entry * (1 - stop_pct / 100):
        signals.append({
            "type": "stop_loss", "level": "sell", "emoji": "\U0001f534",
            "detail": f"down {pct_from_entry:.1f}% from entry (stop -{stop_pct:.0f}%)",
        })

    if price >= entry * (1 + target_pct / 100):
        signals.append({
            "type": "take_profit", "level": "trim", "emoji": "\U0001f7e2",
            "detail": f"up {pct_from_entry:.1f}% from entry (target +{target_pct:.0f}%)",
        })

    if not pd.isna(sma_slow) and price < sma_slow:
        signals.append({
            "type": "trend_break_slow", "level": "sell", "emoji": "\U0001f534",
            "detail": f"close ${price:.2f} below {slow}-day MA ${sma_slow:.2f}",
        })

    if not pd.isna(sma_fast) and price < sma_fast:
        signals.append({
            "type": "trend_break_fast", "level": "watch", "emoji": "\U0001f7e1",
            "detail": f"close ${price:.2f} below {fast}-day MA ${sma_fast:.2f}",
        })

    if (not pd.isna(recent_rsi_max)
            and recent_rsi_max > float(fade["rsi_was_above"])
            and today_rsi < recent_rsi_max
            and vol_ratio < float(fade["volume_dry_ratio"])):
        signals.append({
            "type": "momentum_fade", "level": "watch", "emoji": "\U0001f7e1",
            "detail": (f"RSI rolling over (peaked {recent_rsi_max:.0f}) "
                       f"on drying volume ({vol_ratio:.1f}x avg)"),
        })

    return {
        "ticker": position["ticker"],
        "current_price": price,
        "pct_from_entry": pct_from_entry,
        "signals": signals,
    }
