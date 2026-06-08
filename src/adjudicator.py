def adjudicate(candidate: dict, news: dict, risk: dict, context: dict, caps: dict) -> dict:
    """Combine the deterministic score with agent verdicts. Pure function.

    Veto wins absolutely. All boosts/demotes are fixed caps. Final score is clamped 0-100.
    """
    ticker = candidate["ticker"]
    base = float(candidate["score"])
    regime = context.get("regime", "neutral")

    if risk.get("veto"):
        return {
            "ticker": ticker,
            "base_score": base,
            "final_score": base,
            "vetoed": True,
            "veto_reason": risk.get("reason", ""),
            "news": news,
            "risk": risk,
            "regime": regime,
            "adjustments": [],
        }

    final = base
    adjustments = []

    level = risk.get("risk_level", "low")
    if level == "high":
        final -= caps["risk_high"]
        adjustments.append(f"-{caps['risk_high']:.0f} high risk")
    elif level == "medium":
        final -= caps["risk_medium"]
        adjustments.append(f"-{caps['risk_medium']:.0f} medium risk")

    if news.get("catalyst"):
        final += caps["catalyst"]
        adjustments.append(f"+{caps['catalyst']:.0f} catalyst")
    if news.get("sentiment") == "neg":
        final -= caps["news_negative"]
        adjustments.append(f"-{caps['news_negative']:.0f} negative news")

    if regime == "risk_off":
        final -= caps["regime"]
        adjustments.append(f"-{caps['regime']:.0f} risk-off market")
    elif regime == "risk_on":
        final += caps["regime"]
        adjustments.append(f"+{caps['regime']:.0f} risk-on market")

    final = max(0.0, min(100.0, final))

    return {
        "ticker": ticker,
        "base_score": base,
        "final_score": final,
        "vetoed": False,
        "veto_reason": "",
        "news": news,
        "risk": risk,
        "regime": regime,
        "adjustments": adjustments,
    }
