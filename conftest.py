import pytest

from src import secrets_store
from tests.fakes import FakeKeyring


@pytest.fixture(autouse=True)
def _isolate_keyring():
    """Every test gets a fresh in-memory credential store. No test ever reads or
    writes the real OS credential store."""
    secrets_store.set_backend(FakeKeyring())
    yield
    secrets_store.set_backend(None)
