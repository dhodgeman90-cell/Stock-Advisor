from src import secrets_store


def test_set_get_has_and_delete():
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False
    secrets_store.set_secret("ANTHROPIC_API_KEY", "sk-abc")
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") == "sk-abc"
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is True
    secrets_store.delete_secret("ANTHROPIC_API_KEY")
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") is None
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False


def test_delete_missing_is_a_noop():
    # Must not raise even though the underlying keyring delete raises.
    secrets_store.delete_secret("EMAIL_PASSWORD")


def test_get_missing_is_none():
    assert secrets_store.get_secret("EMAIL_PASSWORD") is None


def test_backend_failure_degrades_to_none():
    class Boom:
        def get_password(self, *a):
            raise RuntimeError("no backend")

    secrets_store.set_backend(Boom())
    # A broken/absent credential backend must not crash a run.
    assert secrets_store.get_secret("ANTHROPIC_API_KEY") is None
    assert secrets_store.has_secret("ANTHROPIC_API_KEY") is False


def test_expected_constants():
    assert secrets_store.SERVICE == "StockAdvisor"
    assert set(secrets_store.SECRET_KEYS) == {"ANTHROPIC_API_KEY", "EMAIL_PASSWORD",
                                              "SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_USER_SECRET"}
