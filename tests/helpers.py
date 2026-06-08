import pandas as pd


def make_df(prices, volume=1_000_000):
    """Build an OHLCV DataFrame from a list of close prices.

    Open/High/Low/Close are all set to the price (fine for indicator tests),
    volume is constant unless overridden.
    """
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices,
            "Low": prices,
            "Close": prices,
            "Volume": [volume] * len(prices),
        },
        index=idx,
    )
