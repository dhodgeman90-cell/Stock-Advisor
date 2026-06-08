DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicClient:
    """Minimal adapter: .complete(system, user) -> text. Reads ANTHROPIC_API_KEY from env."""

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 1024):
        import anthropic
        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )
