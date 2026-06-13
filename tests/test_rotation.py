from src import rotation


def _holding(ticker, signals=None, **extra):
    return {"ticker": ticker, "current_price": 100.0, "pct_from_entry": 0.0,
            "signals": signals or [], **extra}


SELL = [{"type": "trailing_stop", "level": "sell", "emoji": "🔴", "detail": "down 13% from peak"}]
TRIM = [{"type": "take_profit", "level": "trim", "emoji": "🟢", "detail": "up 22% from entry"}]


def test_rotation_routes_holdings_by_signal():
    holdings = [
        _holding("AAPL", signals=SELL),                                  # -> exit
        _holding("MSFT", signals=TRIM),                                  # -> trim (take profit)
        _holding("NVDA", congress={"net_side": "sell", "n_members": 2}), # -> trim (smart money out)
        _holding("T"),                                                   # -> hold
    ]
    ranked = [
        {"ticker": "SMCI", "final_score": 80, "congress": {"net_side": "buy", "n_members": 1}, "insider": None},
        {"ticker": "AAPL", "final_score": 75, "congress": None, "insider": None},   # held -> not an add
        {"ticker": "F", "final_score": 50, "congress": None, "insider": None},      # below conviction
    ]
    plan = rotation.build_rotation_plan(holdings, ranked, conviction=65, max_adds=3)
    assert {e["ticker"] for e in plan["exits"]} == {"AAPL"}
    assert {e["ticker"] for e in plan["trims"]} == {"MSFT", "NVDA"}
    assert {e["ticker"] for e in plan["adds"]} == {"SMCI"}
    assert {e["ticker"] for e in plan["hold"]} == {"T"}


def test_add_is_flagged_high_conviction_when_smart_money_corroborates():
    plan = rotation.build_rotation_plan(
        holdings=[],
        ranked=[{"ticker": "SMCI", "final_score": 80,
                 "congress": {"net_side": "buy", "n_members": 1}, "insider": None}],
        conviction=65, max_adds=3,
    )
    assert plan["adds"][0]["conviction"] == "high"


def test_add_is_normal_conviction_without_corroboration():
    plan = rotation.build_rotation_plan(
        holdings=[],
        ranked=[{"ticker": "XYZ", "final_score": 70, "congress": None, "insider": None}],
        conviction=65, max_adds=3,
    )
    assert plan["adds"][0]["conviction"] == "normal"


def test_adds_respect_max_and_conviction_floor():
    ranked = [
        {"ticker": "A", "final_score": 90, "congress": None, "insider": None},
        {"ticker": "B", "final_score": 80, "congress": None, "insider": None},
        {"ticker": "C", "final_score": 70, "congress": None, "insider": None},
        {"ticker": "D", "final_score": 60, "congress": None, "insider": None},  # below floor
    ]
    plan = rotation.build_rotation_plan([], ranked, conviction=65, max_adds=2)
    assert [e["ticker"] for e in plan["adds"]] == ["A", "B"]   # capped at 2, D excluded


def test_empty_inputs_give_empty_plan():
    plan = rotation.build_rotation_plan([], [], conviction=65, max_adds=3)
    assert plan == {"exits": [], "trims": [], "adds": [], "hold": []}
