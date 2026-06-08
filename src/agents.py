import json

NEUTRAL_NEWS = {
    "catalyst": False,
    "catalyst_type": "",
    "sentiment": "neutral",
    "summary": "news agent unavailable",
}
NEUTRAL_RISK = {
    "risk_level": "low",
    "red_flags": [],
    "veto": False,
    "reason": "risk agent unavailable (treated as no opinion)",
}
NEUTRAL_CONTEXT = {"regime": "neutral", "note": "context agent unavailable"}


def extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of a model reply."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def news_agent(client, ticker: str, headlines: list) -> dict:
    if not headlines:
        return {**NEUTRAL_NEWS, "summary": "no recent headlines"}
    system = (
        "You are a financial news analyst. Given recent headlines for a stock, "
        "decide whether there is a real catalyst, its type, and overall sentiment. "
        "Respond ONLY with a JSON object with keys: catalyst (true/false), "
        "catalyst_type (string), sentiment (one of: pos, neutral, neg), "
        "summary (one sentence)."
    )
    user = f"Ticker: {ticker}\nHeadlines:\n" + "\n".join(f"- {h}" for h in headlines)
    try:
        data = extract_json(client.complete(system, user))
        sentiment = data.get("sentiment")
        return {
            "catalyst": bool(data["catalyst"]),
            "catalyst_type": str(data.get("catalyst_type", "")),
            "sentiment": sentiment if sentiment in ("pos", "neutral", "neg") else "neutral",
            "summary": str(data.get("summary", "")),
        }
    except Exception:
        return dict(NEUTRAL_NEWS)


def risk_agent(client, ticker: str, recent_closes: list, headlines: list) -> dict:
    system = (
        "You are a risk analyst for short-term stock trades. Identify reasons NOT to buy: "
        "pump-and-dump signs, imminent earnings (gap risk), dilution/offering, trading halts, "
        "lawsuits/fraud, or a price spike on no news. Respond ONLY with a JSON object with keys: "
        "risk_level (one of: low, medium, high), red_flags (array of short strings), "
        "veto (true/false; true ONLY for severe danger such as an active fraud probe), "
        "reason (one sentence)."
    )
    closes = ", ".join(f"{c:.2f}" for c in recent_closes[-10:])
    hl = "\n".join(f"- {h}" for h in headlines) if headlines else "(none)"
    user = f"Ticker: {ticker}\nRecent closes: {closes}\nHeadlines:\n{hl}"
    try:
        data = extract_json(client.complete(system, user))
        level = data.get("risk_level")
        return {
            "risk_level": level if level in ("low", "medium", "high") else "low",
            "red_flags": [str(x) for x in data.get("red_flags", [])][:5],
            "veto": bool(data.get("veto", False)),
            "reason": str(data.get("reason", "")),
        }
    except Exception:
        return dict(NEUTRAL_RISK)


def context_agent(client, market_summary: str) -> dict:
    system = (
        "You are a market strategist. Given a short market summary, classify the regime. "
        "Respond ONLY with a JSON object with keys: regime (one of: risk_on, neutral, risk_off), "
        "note (one sentence)."
    )
    user = f"Market summary:\n{market_summary}"
    try:
        data = extract_json(client.complete(system, user))
        regime = data.get("regime")
        return {
            "regime": regime if regime in ("risk_on", "neutral", "risk_off") else "neutral",
            "note": str(data.get("note", "")),
        }
    except Exception:
        return dict(NEUTRAL_CONTEXT)
