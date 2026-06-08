def _parse_news_items(items: list, limit: int = 5) -> list:
    """Extract headline strings from yfinance news items (new and old shapes)."""
    titles = []
    for it in items[:limit]:
        content = it.get("content") if isinstance(it.get("content"), dict) else None
        title = (content or {}).get("title") or it.get("title")
        if title:
            titles.append(title)
    return titles


def get_headlines(ticker: str, limit: int = 5) -> list:
    """Fetch recent headlines for a ticker via yfinance. Network call — not unit-tested."""
    import yfinance as yf
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    return _parse_news_items(items, limit)
