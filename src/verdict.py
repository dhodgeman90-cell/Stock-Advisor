"""One clear Buy / Watch / Avoid call per candidate, plus the single plain-English reason
driving it. Pure functions, no I/O, so the markdown and HTML briefings share ONE source of
wording (they were hand-synced twin f-strings that could drift) and the logic is unit-testable.

`classify(r, buy_threshold)` takes an adjudicator result dict `r` (see adjudicator.adjudicate)
and returns {"call", "reason", "confidence", "contradiction"}.
"""

# adjudicator note() keys -> short plain-English phrase for the reason line.
_PHRASE = {
    "risk_high": "high risk",
    "risk_medium": "moderate risk",
    "catalyst": "a news catalyst",
    "news_negative": "negative news",
    "regime_off": "a risk-off market",
    "regime_on": "a risk-on market",
    "congress_buy": "congressional buying",
    "congress_sell": "congressional selling",
    "insider_buy": "insider buying",
    "insider_sell": "insider selling",
    "analyst_bull": "bullish analysts",
    "analyst_bear": "bearish analysts",
    "earnings_soon": "earnings due soon",
    "edgar_severe": "a severe SEC filing",
    "edgar_catalyst": "a material SEC 8-K",
    "edgar_adverse": "an adverse SEC 8-K",
    "activist_stake": "an activist 13D stake",
    "options_bull": "unusual call flow",
    "options_bear": "unusual put flow",
    "squeeze_setup": "a short-squeeze setup",
    "crowded_short": "a crowded short",
    "estimates_up": "rising estimates",
    "estimates_down": "falling estimates",
    "wsb_buzz": "WSB buzz",
    "wsb_contrarian": "contrarian WSB hype",
}

# Signals that contradict a high score: if the score says Buy while one of these fired, the
# call is knocked down to Watch and the conflict is named. This is the "100/100 but analysts
# bearish, target -8%" case, reconciled at the source instead of dumped on the reader.
_CONTRADICTORS = {
    "risk_high", "analyst_bear", "edgar_adverse", "edgar_severe",
    "news_negative", "congress_sell", "insider_sell",
    "options_bear", "estimates_down",
}

# Watch spans this many points below the buy line; further below is an Avoid.
_WATCH_BAND = 15


def _phrase(key: str) -> str:
    return _PHRASE.get(key, key.replace("_", " "))


def classify(r: dict, buy_threshold: float = 65, *, underperforming: bool = False) -> dict:
    """Buy/Watch/Avoid + one plain reason for an adjudicated candidate. Pure.

    Degrades gracefully: if `r` carries no structured `adjustment_detail`, the reason falls
    back to a technicals-only note rather than raising.
    """
    if r.get("vetoed"):
        return {"call": "Avoid", "reason": r.get("veto_reason") or "vetoed on risk",
                "confidence": "high", "contradiction": False}

    score = float(r.get("final_score", 0.0))
    detail = r.get("adjustment_detail") or []
    fired = {d["key"] for d in detail}
    contradictors = sorted(fired & _CONTRADICTORS)

    if score >= buy_threshold:
        call = "Buy"
    elif score >= buy_threshold - _WATCH_BAND:
        call = "Watch"
    else:
        call = "Avoid"

    contradiction = False
    if call == "Buy" and contradictors:
        call = "Watch"
        contradiction = True

    if contradiction:
        reason = f"strong score but {_phrase(contradictors[0])} — signals conflict"
    else:
        driver = max(detail, key=lambda d: abs(d["points"]), default=None)
        if driver is None:
            reason = "technicals only, no confirming signals"
        elif driver["points"] >= 0:
            reason = f"driven by {_phrase(driver['key'])}"
        else:
            reason = f"held back by {_phrase(driver['key'])}"

    return {"call": call, "reason": reason,
            "confidence": _confidence(score, buy_threshold, len(fired),
                                      underperforming, contradiction),
            "contradiction": contradiction}


def _confidence(score, buy_threshold, n_signals, underperforming, contradiction) -> str:
    """Coarse confidence tag. Deliberately conservative: the system's own scorecard forces
    every call down to 'low' when it is underperforming its benchmark, so the briefing never
    projects false conviction on a record that hasn't earned it.

    `underperforming` is TRI-STATE: True / False / None, where None means the benchmark
    comparison could not be computed (e.g. the SPY fetch failed). That is an absence of
    evidence, not evidence of absence, so it caps confidence too — otherwise a data outage
    silently promotes every pick to medium/high."""
    if underperforming is None or underperforming or contradiction:
        return "low"
    if score >= buy_threshold + 10 and n_signals >= 2:
        return "high"
    if score >= buy_threshold:
        return "medium"
    return "low"


def demo():
    """ponytail: one runnable check the decision logic holds."""
    # plain Buy, biggest positive driver named
    v = classify({"final_score": 82, "adjustment_detail": [
        {"key": "congress_buy", "points": 18}, {"key": "catalyst", "points": 15}]}, 65)
    assert v["call"] == "Buy" and "congressional buying" in v["reason"], v

    # high score but bearish analysts -> Watch, conflict named
    v = classify({"final_score": 90, "adjustment_detail": [
        {"key": "congress_buy", "points": 18}, {"key": "analyst_bear", "points": -8}]}, 65)
    assert v["call"] == "Watch" and v["contradiction"] and "conflict" in v["reason"], v

    # below the watch band -> Avoid
    assert classify({"final_score": 40, "adjustment_detail": []}, 65)["call"] == "Avoid"

    # veto always Avoid
    assert classify({"vetoed": True, "veto_reason": "fraud probe"}, 65)["call"] == "Avoid"

    # underperforming system forces confidence down even on a clean Buy
    v = classify({"final_score": 85, "adjustment_detail": [{"key": "catalyst", "points": 15}]},
                 65, underperforming=True)
    assert v["confidence"] == "low", v
    print("verdict.demo OK")


if __name__ == "__main__":
    demo()
