from src import trust


def test_corroborated_high_credibility_buzz_is_fully_trusted():
    # Strong technicals + congress buy + insider buy + analyst-grade credibility,
    # no risk flags: the WSB buzz is corroborated from every direction.
    t = trust.social_trust(
        wsb_signal={"mentions": 200, "mentions_change": 150},
        base_score=72,
        congress_signal={"net_side": "buy"},
        insider_signal={"net_side": "buy"},
        risk={"risk_level": "low", "veto": False},
        credibility="high",
    )
    assert t == 1.0


def test_hype_on_weak_name_with_pump_risk_collapses_trust():
    # A mention spike on a weak chart, flagged risky, with low-credibility chatter
    # is exactly the pump pattern that should NOT be trusted.
    t = trust.social_trust(
        wsb_signal={"mentions": 500, "mentions_change": 400},
        base_score=30,
        congress_signal=None,
        insider_signal=None,
        risk={"risk_level": "high", "veto": False},
        credibility="low",
    )
    assert t == 0.0


def test_neutral_inputs_give_middling_trust():
    t = trust.social_trust(
        wsb_signal={"mentions": 40, "mentions_change": 5},
        base_score=50,
        congress_signal=None,
        insider_signal=None,
        risk={"risk_level": "low", "veto": False},
        credibility=None,
    )
    assert 0.3 <= t <= 0.6


def test_trust_is_clamped_to_unit_interval():
    t = trust.social_trust(
        wsb_signal={"mentions": 10, "mentions_change": 1},
        base_score=90, congress_signal={"net_side": "buy"},
        insider_signal={"net_side": "buy"}, risk={"risk_level": "low", "veto": False},
        credibility="high",
    )
    assert 0.0 <= t <= 1.0
