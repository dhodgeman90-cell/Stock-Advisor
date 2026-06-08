class FakeClient:
    """LLM client stand-in that returns a fixed reply string."""

    def __init__(self, reply: str):
        self.reply = reply

    def complete(self, system: str, user: str) -> str:
        return self.reply


class BoomClient:
    """LLM client stand-in that always raises (simulates an outage/bad key)."""

    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("boom")


class FakeSMTP:
    """SMTP stand-in usable as a context manager; records login + sent message."""

    def __init__(self):
        self.logged_in = None
        self.sent_message = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent_message = msg
