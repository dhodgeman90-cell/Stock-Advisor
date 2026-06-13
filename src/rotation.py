"""Daily rotation plan — the 'transition mindset' synthesis.

Each morning, given the current holdings (with their exit signals) and the freshly
adjudicated candidates, decide what to exit, trim, add, or hold. This is a pure,
deterministic recommendation: it never trades, and it respects the existing exit rails
(a 🔴 sell signal always wins). Smart-money selling (congress/insiders leaving) trims a
name even without a technical break; smart-money buying upgrades an add to high conviction.
"""


def _smart_money_sell(holding):
    for key in ("congress", "insider"):
        sig = holding.get(key)
        if sig and sig.get("net_side") == "sell":
            return key
    return None


def _classify_holding(h):
    """Return (bucket, reason) for one holding: 'exit', 'trim', or 'hold'."""
    levels = {s.get("level") for s in h.get("signals", [])}
    if "sell" in levels:
        detail = next((s["detail"] for s in h["signals"] if s.get("level") == "sell"), "exit signal")
        return "exit", detail
    if "trim" in levels:
        detail = next((s["detail"] for s in h["signals"] if s.get("level") == "trim"), "take profit")
        return "trim", detail
    seller = _smart_money_sell(h)
    if seller:
        return "trim", f"{seller} selling"
    return "hold", ""


def _add_conviction(candidate):
    for key in ("congress", "insider"):
        sig = candidate.get(key)
        if sig and sig.get("net_side") == "buy":
            return "high"
    return "normal"


def build_rotation_plan(holdings, ranked, conviction=65, max_adds=3):
    """Synthesize the morning rotation: {exits, trims, adds, hold}."""
    exits, trims, hold = [], [], []
    for h in holdings:
        bucket, reason = _classify_holding(h)
        entry = {"ticker": h["ticker"], "reason": reason}
        if bucket == "exit":
            exits.append(entry)
        elif bucket == "trim":
            trims.append(entry)
        else:
            hold.append({"ticker": h["ticker"]})

    held = {h["ticker"] for h in holdings}
    adds = []
    for c in ranked:
        if len(adds) >= max_adds:
            break
        if c["ticker"] in held or c["final_score"] < conviction:
            continue
        conv = _add_conviction(c)
        reason = "high-conviction setup" if conv == "high" else "top-ranked momentum"
        adds.append({"ticker": c["ticker"], "final_score": c["final_score"],
                     "conviction": conv, "reason": reason})

    return {"exits": exits, "trims": trims, "adds": adds, "hold": hold}
