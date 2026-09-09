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

# What a would-be Buy is called while `adds_paused` is set. Measured 2026-09-09: 332 "Buy:"
# verdicts had shipped across every briefing while buys were nominally paused, because the flag
# only zeroed the rotation adds. The screen still has an opinion worth showing — it just may not
# call it a Buy.
_PAUSED_CALL = "Candidate"


def _phrase(key: str) -> str:
    return _PHRASE.get(key, key.replace("_", " "))


def classify(r: dict, buy_threshold: float = 65, *, underperforming: bool = False,
             adds_paused: bool = False) -> dict:
    """Buy/Watch/Avoid + one plain reason for an adjudicated candidate. Pure.

    Degrades gracefully: if `r` carries no structured `adjustment_detail`, the reason falls
    back to a technicals-only note rather than raising.

    `adds_paused` mirrors the live config flag. When buys are withheld the shortlist must not
    say "Buy" — see the note on _PAUSED_CALL. `underperforming` is accepted and ignored; it
    fed the old ordinal confidence tag, which is gone (see confidence_text).
    """
    if r.get("vetoed"):
        return {"call": "Avoid", "reason": r.get("veto_reason") or "vetoed on risk",
                "confidence": None, "contradiction": False}

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

    # Buys withheld -> the label must say so. A contradiction already knocked the call down to
    # Watch above, which is the stronger statement, so only a surviving Buy is relabelled.
    if call == "Buy" and adds_paused:
        call = _PAUSED_CALL

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

    return {"call": call, "reason": reason, "confidence": None,
            "contradiction": contradiction}


def confidence_text(summary) -> str:
    """The realised beat-SPY rate, or an explicit statement that there isn't one yet.

    This REPLACES the old ordinal confidence tag. That tag short-circuited to "low" whenever
    the system was underperforming, and the system has underperformed continuously since it
    shipped, so all 368 tags ever printed read "low confidence" — a constant carrying zero
    information, and the specific thing the owner complained about.

    The honest substitute is the frequency actually observed: how often past calls beat SPY,
    with the sample size attached. Below the maturity floor (`enough`) or with no computable
    rate it says so in words and quotes no number, because an absent benchmark is an absence
    of evidence, not a clean bill of health.
    """
    summary = summary or {}
    rate, n = summary.get("beat_spy_rate"), summary.get("n_matured")
    if not summary.get("enough") or rate is None or not n:
        return "no measured track record yet"
    return f"{rate:.0f}% of past calls beat SPY at +5d (n={n})"


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

    # buys paused -> the label says Candidate, not Buy, but keeps its reason
    v = classify({"final_score": 85, "adjustment_detail": [{"key": "catalyst", "points": 15}]},
                 65, adds_paused=True)
    assert v["call"] == "Candidate" and "news catalyst" in v["reason"], v

    # confidence is a measured rate or an explicit absence — never a bare ordinal
    assert "45%" in confidence_text({"enough": True, "beat_spy_rate": 45.0, "n_matured": 480})
    assert "no measured" in confidence_text(None)
    print("verdict.demo OK")


if __name__ == "__main__":
    demo()
