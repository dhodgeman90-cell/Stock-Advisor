import datetime as dt
from pathlib import Path

from src import config, data, scoring, report

ROOT = Path(__file__).resolve().parent.parent


def run() -> str:
    wl = config.load_watchlist()
    weights = config.load_weights()
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)

    data_dir = ROOT / "data"
    reports_dir = ROOT / "reports"

    scored = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, lookback)
        ok, reason = data.validate(df, ticker)
        if ok:
            data.save_cache(df, ticker, data_dir)
        else:
            # fall back to last good cache; flag clearly if unusable
            df = data.load_cache(ticker, data_dir)
            cache_ok, _ = data.validate(df, ticker) if df is not None else (False, "")
            if not cache_ok:
                scored.append({
                    "ticker": ticker,
                    "excluded": True,
                    "reason": f"{reason} (no valid cache)",
                })
                continue
        scored.append(scoring.score_ticker(df, ticker, weights, settings))

    date_str = dt.date.today().isoformat()
    text = report.render_report(scored, date_str)

    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
    print(text)
    return text


if __name__ == "__main__":
    run()
