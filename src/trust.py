STRONG_TECHNICALS = 60.0    # base score at/above which the chart corroborates the buzz
WEAK_TECHNICALS = 40.0      # base score below which a mention spike looks like hype
HYPE_SPIKE = 50             # 24h mention jump that counts as a surge

_CREDIBILITY = {"high": 0.25, "med": 0.10, "low": -0.20}


def social_trust(wsb_signal, base_score, congress_signal, insider_signal, risk, credibility) -> float:
    """How much to trust r/wallstreetbets buzz *in this specific situation*, in [0, 1].

    Social media is only sometimes a good source, so trust is contextual rather than a
    fixed discount: it climbs when the buzz is corroborated by the chart, congressional
    buying, insider buying, or substantive (high-credibility) discussion — and collapses
    on the classic pump pattern (a mention spike on a weak chart that the risk agent has
    flagged). The result scales the social cap in the adjudicator; direction (bullish vs
    contrarian) is decided there.
    """
    wsb_signal = wsb_signal or {}
    risk = risk or {}
    trust = 0.4

    if base_score is not None and base_score >= STRONG_TECHNICALS:
        trust += 0.20
    if congress_signal and congress_signal.get("net_side") == "buy":
        trust += 0.20
    if insider_signal and insider_signal.get("net_side") == "buy":
        trust += 0.15
    trust += _CREDIBILITY.get(credibility, 0.0)

    if risk.get("veto") or risk.get("risk_level") == "high":
        trust -= 0.30

    change = wsb_signal.get("mentions_change")
    if change is not None and change >= HYPE_SPIKE and base_score is not None and base_score < WEAK_TECHNICALS:
        trust -= 0.25

    return round(max(0.0, min(1.0, trust)), 4)
