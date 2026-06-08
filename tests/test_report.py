from src import report


def test_report_ranks_candidates_and_lists_excluded():
    scored = [
        {"ticker": "LOW", "excluded": False, "score": 60.0,
         "components": {"trend": 1, "momentum": 1, "breakout": 0.5,
                        "volume": 0.5, "pullback": 0}},
        {"ticker": "HIGH", "excluded": False, "score": 85.0,
         "components": {"trend": 1, "momentum": 1, "breakout": 1,
                        "volume": 1, "pullback": 0}},
        {"ticker": "BAD", "excluded": True, "reason": "price $2.00 below floor $5.00"},
    ]
    text = report.render_report(scored, "2026-06-08")

    assert "2026-06-08" in text
    # HIGH (85) must appear before LOW (60) in the ranked section
    assert text.index("HIGH") < text.index("LOW")
    # excluded ticker shows with its reason
    assert "BAD" in text
    assert "below floor" in text
