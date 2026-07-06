import datetime as dt

from src import edgar

TODAY = dt.date(2026, 6, 17)


def _filings(rows):
    """rows = list of (form, items, date) -> the three parallel arrays SEC returns."""
    forms = [r[0] for r in rows]
    items = [r[1] for r in rows]
    dates = [r[2] for r in rows]
    return forms, items, dates


def test_signal_asof_excludes_future_filings():
    # earnings 8-K in the past; a bankruptcy 8-K in the FUTURE relative to the as-of date.
    forms, items, dates = _filings([
        ("8-K", "2.02", "2026-06-01"),      # earnings -> catalyst (known by as-of)
        ("8-K", "1.03", "2026-06-20"),      # bankruptcy -> severe (NOT yet known)
    ])
    sig = edgar.signal_asof(forms, items, dates, "2026-06-10", window_days=30)
    assert sig["catalyst"] is True and sig["severe"] is False   # future filing excluded
    assert sig["as_of"] == "2026-06-01"
    # ...and once the as-of moves past the bankruptcy, it counts.
    later = edgar.signal_asof(forms, items, dates, "2026-06-25", window_days=30)
    assert later["severe"] is True


def test_signal_asof_respects_window_lower_bound():
    forms, items, dates = _filings([("8-K", "2.02", "2026-05-01")])   # 40+ days before
    sig = edgar.signal_asof(forms, items, dates, "2026-06-17", window_days=30)
    assert sig["catalyst"] is False        # too old, outside the 30-day window


def test_parse_catalyst_from_8k_items():
    forms, items, dates = _filings([
        ("8-K", "2.02,9.01", "2026-06-10"),     # earnings -> catalyst
        ("8-K", "5.07,9.01", "2026-06-05"),     # shareholder vote -> ignored
    ])
    out = edgar._parse_filings(forms, items, dates, today=TODAY)
    assert out["catalyst"] is True
    assert "reported earnings" in out["catalyst_types"]
    assert out["severe"] is False and out["negative"] is False
    assert out["as_of"] == "2026-06-10"


def test_parse_severe_item_flags_risk():
    forms, items, dates = _filings([("8-K", "3.01", "2026-06-12")])    # delisting
    out = edgar._parse_filings(forms, items, dates, today=TODAY)
    assert out["severe"] is True
    assert out["severe_reason"] == "delisting notice"


def test_parse_negative_item():
    forms, items, dates = _filings([("8-K", "4.01", "2026-06-12")])    # auditor change
    out = edgar._parse_filings(forms, items, dates, today=TODAY)
    assert out["negative"] is True and out["catalyst"] is False


def test_parse_window_excludes_old_filings():
    forms, items, dates = _filings([("8-K", "2.02", "2026-01-01")])    # >30d ago
    out = edgar._parse_filings(forms, items, dates, today=TODAY, window_days=30)
    assert out["catalyst"] is False and out["as_of"] is None


def test_parse_activist_13d_and_form4_count():
    forms, items, dates = _filings([
        ("SC 13D", "", "2026-06-09"),
        ("SC 13G", "", "2026-06-09"),      # passive -> NOT activist
        ("4", "", "2026-06-08"),
        ("4", "", "2026-06-07"),
    ])
    out = edgar._parse_filings(forms, items, dates, today=TODAY)
    assert out["activist"] is True
    assert out["form4_count"] == 2


def test_get_sec_signal_unknown_ticker_is_neutral():
    out = edgar.get_sec_signal("ZZZZ", {"AAPL": 320193})
    assert out == edgar.NEUTRAL_SEC


def test_get_sec_signal_uses_injected_fetch():
    payload = {"filings": {"recent": {
        "form": ["8-K"], "items": ["1.01"], "filingDate": ["2026-06-15"]}}}
    out = edgar.get_sec_signal("AAPL", {"AAPL": 320193},
                               fetch=lambda cik: payload, today=TODAY)
    assert out["catalyst"] is True
    assert "entered a material agreement" in out["catalyst_types"]


def test_get_sec_signal_falls_back_on_error():
    def boom(cik):
        raise RuntimeError("sec down")
    out = edgar.get_sec_signal("AAPL", {"AAPL": 320193}, fetch=boom)
    assert out == edgar.NEUTRAL_SEC


def test_load_cik_map_parses_and_caches(tmp_path):
    cache = tmp_path / "cik.json"
    payload = {"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple"}}
    out = edgar.load_cik_map(fetch=lambda: payload, cache_path=cache)
    assert out == {"AAPL": 320193}
    assert cache.exists()


def test_load_cik_map_falls_back_to_cache(tmp_path):
    cache = tmp_path / "cik.json"
    edgar.load_cik_map(fetch=lambda: {"0": {"cik_str": 1, "ticker": "x"}}, cache_path=cache)

    def boom():
        raise RuntimeError("down")
    out = edgar.load_cik_map(fetch=boom, cache_path=cache)
    assert out == {"X": 1}
