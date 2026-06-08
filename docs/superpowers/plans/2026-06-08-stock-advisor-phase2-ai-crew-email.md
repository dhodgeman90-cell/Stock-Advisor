# Stock Advisor — Phase 2: AI Crew + Email — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded crew of AI agents (News, Risk, Context) on Claude Haiku that annotate the top-scored stocks, a rules-based adjudicator that combines their verdicts with the deterministic score (capped boosts/demotes + hard veto), and a daily email briefing — all degrading gracefully when no API key or email is configured.

**Architecture:** Builds on the Phase 1 deterministic core. After scoring, the top N candidates go to three LLM agents (each with a strict JSON contract and a neutral "no opinion" fallback on any failure). A pure-rules adjudicator applies capped adjustments and an absolute veto. Output is an enriched markdown briefing, saved to `reports/` and optionally emailed. The AI and email are injected via simple interfaces so the whole layer is unit-tested with **no network and no API cost**.

**Tech Stack:** Python 3.11+, anthropic SDK (Claude Haiku `claude-haiku-4-5`), python-dotenv, yfinance (news), smtplib/email (built-in). Tests use fake clients — never the real API.

**Project root:** `C:\VS Code\Stock Advisor` (Phase 1 merged to `master`).

> **Run commands in this plan** use the project's virtual environment. On Windows PowerShell that is:
> `& .\.venv\Scripts\python.exe -m pytest ...` and `& .\.venv\Scripts\python.exe -m src.main`.

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` (modify) | Add `anthropic`, `python-dotenv` |
| `.env.example` (create) | Template for API key + email settings (real `.env` is git-ignored) |
| `config/adjudicator.yaml` (create) | Adjustment caps (catalyst/news/risk/regime) |
| `src/config.py` (modify) | Add `load_adjudicator()` |
| `src/agents.py` (create) | `extract_json` + `news_agent` / `risk_agent` / `context_agent`, each with neutral fallback |
| `src/llm.py` (create) | Thin real Anthropic client adapter (`AnthropicClient.complete`) |
| `src/news.py` (create) | `_parse_news_items` (pure) + `get_headlines` (yfinance, network) |
| `src/adjudicator.py` (create) | `adjudicate()` — pure rules: caps + veto + clamp |
| `src/briefing.py` (create) | `render_briefing()` (pure) + `send_email()` (injectable SMTP) |
| `src/main.py` (modify) | Wire agents + adjudicator + briefing; gate on API key/email; graceful fallback |
| `tests/fakes.py` (create) | `FakeClient`, `BoomClient`, `FakeSMTP` test doubles |
| `tests/test_agents.py` (create) | Agent parsing + fallback tests |
| `tests/test_adjudicator.py` (create) | Adjudicator rules tests |
| `tests/test_briefing.py` (create) | Briefing render + email send tests |
| `tests/test_news.py` (create) | News-item parser tests |
| `tests/test_config.py` (modify) | Add `load_adjudicator` test |

**Agent JSON contracts (used consistently across tasks):**
- News: `{"catalyst": bool, "catalyst_type": str, "sentiment": "pos"|"neutral"|"neg", "summary": str}`
- Risk: `{"risk_level": "low"|"medium"|"high", "red_flags": [str], "veto": bool, "reason": str}`
- Context: `{"regime": "risk_on"|"neutral"|"risk_off", "note": str}`

---

## Task 1: Dependencies, adjudicator config, and `.env` template

**Files:**
- Modify: `requirements.txt`
- Create: `.env.example`, `config/adjudicator.yaml`
- Modify: `src/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Update `requirements.txt`** (full new contents)

```
pandas>=2.0
yfinance>=0.2.40
PyYAML>=6.0
pytest>=8.0
anthropic>=0.40
python-dotenv>=1.0
```

- [ ] **Step 2: Install the two new libraries**

Run: `& .\.venv\Scripts\python.exe -m pip install anthropic python-dotenv`
Expected: "Successfully installed anthropic-... python-dotenv-..."

- [ ] **Step 3: Create `.env.example`**

```
# === Anthropic API (Phase 2 AI agents) ===
# Create a key at https://console.anthropic.com
# IMPORTANT: set a $5/month spend limit in Console → Settings → Limits.
ANTHROPIC_API_KEY=

# === Email briefing (optional) ===
# For Gmail, create an "App Password" (Google Account → Security → App passwords).
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=465
EMAIL_USER=
EMAIL_PASSWORD=
EMAIL_TO=
```

- [ ] **Step 4: Create `config/adjudicator.yaml`**

```yaml
caps:
  catalyst: 15        # +points when the News agent finds a real catalyst
  news_negative: 10   # -points on negative news sentiment
  risk_high: 20       # -points when Risk agent says risk is high
  risk_medium: 8      # -points when Risk agent says risk is medium
  regime: 5           # +/- global points from the Context agent's market regime
```

- [ ] **Step 5: Write the failing test** — add to `tests/test_config.py`

```python
def test_load_adjudicator_returns_floats(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "watchlist.yaml").write_text("tickers:\n  - aapl\n", encoding="utf-8")
    (cfg / "weights.yaml").write_text("weights:\n  breakout: 30\n", encoding="utf-8")
    (cfg / "adjudicator.yaml").write_text(
        "caps:\n  catalyst: 15\n  risk_high: 20\n", encoding="utf-8"
    )
    caps = config.load_adjudicator(cfg)
    assert caps == {"catalyst": 15.0, "risk_high": 20.0}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_config.py::test_load_adjudicator_returns_floats -v`
Expected: FAIL (`AttributeError: module 'src.config' has no attribute 'load_adjudicator'`)

- [ ] **Step 7: Add `load_adjudicator` to `src/config.py`** (append this function)

```python
def load_adjudicator(config_dir=CONFIG_DIR) -> dict:
    data = _load("adjudicator.yaml", config_dir)
    caps = data.get("caps")
    if not caps:
        raise ValueError("adjudicator.yaml must contain a 'caps' mapping")
    return {k: float(v) for k, v in caps.items()}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (all config tests)

- [ ] **Step 9: Commit**

```powershell
git add requirements.txt .env.example config/adjudicator.yaml src/config.py tests/test_config.py
git commit -m "feat: phase 2 deps, adjudicator caps config, env template"
```

---

## Task 2: Test doubles (`tests/fakes.py`)

**Files:**
- Create: `tests/fakes.py`

- [ ] **Step 1: Create the fakes** (shared by several test files; no network)

```python
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
```

- [ ] **Step 2: Commit**

```powershell
git add tests/fakes.py
git commit -m "test: add fake LLM + SMTP test doubles"
```

---

## Task 3: The agent crew (`src/agents.py`)

**Files:**
- Create: `src/agents.py`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_agents.py`

```python
from src import agents
from tests.fakes import FakeClient, BoomClient


def test_extract_json_from_fenced_text():
    text = "Here you go:\n```json\n{\"a\": 1}\n```"
    assert agents.extract_json(text) == {"a": 1}


def test_news_agent_parses_catalyst():
    reply = ('{"catalyst": true, "catalyst_type": "earnings", '
             '"sentiment": "pos", "summary": "Beat estimates."}')
    out = agents.news_agent(FakeClient(reply), "AAPL", ["Apple beats earnings"])
    assert out["catalyst"] is True
    assert out["sentiment"] == "pos"


def test_news_agent_no_headlines_is_neutral():
    out = agents.news_agent(FakeClient("{}"), "AAPL", [])
    assert out["catalyst"] is False
    assert out["sentiment"] == "neutral"


def test_news_agent_falls_back_on_error():
    out = agents.news_agent(BoomClient(), "AAPL", ["something"])
    assert out["catalyst"] is False
    assert out["sentiment"] == "neutral"


def test_risk_agent_parses_veto():
    reply = ('{"risk_level": "high", "red_flags": ["fraud probe"], '
             '"veto": true, "reason": "Active SEC fraud investigation."}')
    out = agents.risk_agent(FakeClient(reply), "XYZ", [10.0, 11.0], ["probe opened"])
    assert out["veto"] is True
    assert out["risk_level"] == "high"


def test_risk_agent_falls_back_to_no_opinion_on_error():
    out = agents.risk_agent(BoomClient(), "XYZ", [10.0, 11.0], [])
    assert out["veto"] is False
    assert out["risk_level"] == "low"   # neutral = no demote, no veto


def test_risk_agent_falls_back_on_junk_reply():
    out = agents.risk_agent(FakeClient("not json at all"), "XYZ", [10.0], [])
    assert out["veto"] is False


def test_context_agent_parses_regime():
    out = agents.context_agent(
        FakeClient('{"regime": "risk_off", "note": "Rates rising."}'),
        "market is jittery",
    )
    assert out["regime"] == "risk_off"


def test_context_agent_falls_back_on_error():
    out = agents.context_agent(BoomClient(), "anything")
    assert out["regime"] == "neutral"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_agents.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.agents'`)

- [ ] **Step 3: Write `src/agents.py`**

```python
import json

NEUTRAL_NEWS = {
    "catalyst": False,
    "catalyst_type": "",
    "sentiment": "neutral",
    "summary": "news agent unavailable",
}
NEUTRAL_RISK = {
    "risk_level": "low",
    "red_flags": [],
    "veto": False,
    "reason": "risk agent unavailable (treated as no opinion)",
}
NEUTRAL_CONTEXT = {"regime": "neutral", "note": "context agent unavailable"}


def extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of a model reply."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def news_agent(client, ticker: str, headlines: list) -> dict:
    if not headlines:
        return {**NEUTRAL_NEWS, "summary": "no recent headlines"}
    system = (
        "You are a financial news analyst. Given recent headlines for a stock, "
        "decide whether there is a real catalyst, its type, and overall sentiment. "
        "Respond ONLY with a JSON object with keys: catalyst (true/false), "
        "catalyst_type (string), sentiment (one of: pos, neutral, neg), "
        "summary (one sentence)."
    )
    user = f"Ticker: {ticker}\nHeadlines:\n" + "\n".join(f"- {h}" for h in headlines)
    try:
        data = extract_json(client.complete(system, user))
        sentiment = data.get("sentiment")
        return {
            "catalyst": bool(data["catalyst"]),
            "catalyst_type": str(data.get("catalyst_type", "")),
            "sentiment": sentiment if sentiment in ("pos", "neutral", "neg") else "neutral",
            "summary": str(data.get("summary", "")),
        }
    except Exception:
        return dict(NEUTRAL_NEWS)


def risk_agent(client, ticker: str, recent_closes: list, headlines: list) -> dict:
    system = (
        "You are a risk analyst for short-term stock trades. Identify reasons NOT to buy: "
        "pump-and-dump signs, imminent earnings (gap risk), dilution/offering, trading halts, "
        "lawsuits/fraud, or a price spike on no news. Respond ONLY with a JSON object with keys: "
        "risk_level (one of: low, medium, high), red_flags (array of short strings), "
        "veto (true/false; true ONLY for severe danger such as an active fraud probe), "
        "reason (one sentence)."
    )
    closes = ", ".join(f"{c:.2f}" for c in recent_closes[-10:])
    hl = "\n".join(f"- {h}" for h in headlines) if headlines else "(none)"
    user = f"Ticker: {ticker}\nRecent closes: {closes}\nHeadlines:\n{hl}"
    try:
        data = extract_json(client.complete(system, user))
        level = data.get("risk_level")
        return {
            "risk_level": level if level in ("low", "medium", "high") else "low",
            "red_flags": [str(x) for x in data.get("red_flags", [])][:5],
            "veto": bool(data.get("veto", False)),
            "reason": str(data.get("reason", "")),
        }
    except Exception:
        return dict(NEUTRAL_RISK)


def context_agent(client, market_summary: str) -> dict:
    system = (
        "You are a market strategist. Given a short market summary, classify the regime. "
        "Respond ONLY with a JSON object with keys: regime (one of: risk_on, neutral, risk_off), "
        "note (one sentence)."
    )
    user = f"Market summary:\n{market_summary}"
    try:
        data = extract_json(client.complete(system, user))
        regime = data.get("regime")
        return {
            "regime": regime if regime in ("risk_on", "neutral", "risk_off") else "neutral",
            "note": str(data.get("note", "")),
        }
    except Exception:
        return dict(NEUTRAL_CONTEXT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_agents.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/agents.py tests/test_agents.py
git commit -m "feat: bounded News/Risk/Context agents with neutral fallbacks"
```

---

## Task 4: Real Anthropic client (`src/llm.py`)

**Files:**
- Create: `src/llm.py`

> Thin adapter over the anthropic SDK. Not unit-tested (it only calls the real API, which agents reach through the `client.complete` interface that tests fake). It's exercised in the Task 8 real run.

- [ ] **Step 1: Write `src/llm.py`**

```python
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
```

- [ ] **Step 2: Commit**

```powershell
git add src/llm.py
git commit -m "feat: thin Anthropic (Claude Haiku) client adapter"
```

---

## Task 5: News fetching (`src/news.py`)

**Files:**
- Create: `src/news.py`
- Test: `tests/test_news.py`

- [ ] **Step 1: Write the failing test** — `tests/test_news.py` (tests the pure parser; the network call is not unit-tested)

```python
from src import news


def test_parse_new_style_items():
    items = [{"content": {"title": "Apple soars on earnings"}}]
    assert news._parse_news_items(items) == ["Apple soars on earnings"]


def test_parse_old_style_items():
    items = [{"title": "Legacy headline"}]
    assert news._parse_news_items(items) == ["Legacy headline"]


def test_parse_respects_limit_and_skips_titleless():
    items = [
        {"content": {"title": "One"}},
        {"content": {}},                 # no title -> skipped
        {"title": "Two"},
        {"title": "Three"},
    ]
    assert news._parse_news_items(items, limit=2) == ["One"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_news.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.news'`)

- [ ] **Step 3: Write `src/news.py`**

```python
def _parse_news_items(items: list, limit: int = 5) -> list:
    """Extract headline strings from yfinance news items (new and old shapes)."""
    titles = []
    for it in items[:limit]:
        content = it.get("content") if isinstance(it.get("content"), dict) else None
        title = (content or {}).get("title") or it.get("title")
        if title:
            titles.append(title)
    return titles


def get_headlines(ticker: str, limit: int = 5) -> list:
    """Fetch recent headlines for a ticker via yfinance. Network call — not unit-tested."""
    import yfinance as yf
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    return _parse_news_items(items, limit)
```

> Note on the limit test: with `limit=2` the parser looks at the first two items only — `{"content": {"title": "One"}}` yields "One", and `{"content": {}}` has no title and is skipped — so the result is `["One"]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_news.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/news.py tests/test_news.py
git commit -m "feat: per-ticker headline fetching via yfinance"
```

---

## Task 6: Adjudicator (`src/adjudicator.py`)

**Files:**
- Create: `src/adjudicator.py`
- Test: `tests/test_adjudicator.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_adjudicator.py`

```python
from src import adjudicator

CAPS = {"catalyst": 15, "news_negative": 10, "risk_high": 20, "risk_medium": 8, "regime": 5}
NEUTRAL_NEWS = {"catalyst": False, "catalyst_type": "", "sentiment": "neutral", "summary": ""}
NEUTRAL_RISK = {"risk_level": "low", "red_flags": [], "veto": False, "reason": ""}
NEUTRAL_CTX = {"regime": "neutral", "note": ""}


def test_veto_excludes_and_keeps_base():
    risk = {"risk_level": "high", "red_flags": ["fraud"], "veto": True, "reason": "fraud probe"}
    out = adjudicator.adjudicate({"ticker": "X", "score": 80}, NEUTRAL_NEWS, risk, NEUTRAL_CTX, CAPS)
    assert out["vetoed"] is True
    assert out["final_score"] == 80
    assert out["veto_reason"] == "fraud probe"


def test_high_risk_and_catalyst_net_adjustment():
    news = {"catalyst": True, "catalyst_type": "deal", "sentiment": "pos", "summary": ""}
    risk = {"risk_level": "high", "red_flags": [], "veto": False, "reason": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 80}, news, risk, NEUTRAL_CTX, CAPS)
    assert out["vetoed"] is False
    assert out["final_score"] == 75   # 80 - 20 (high risk) + 15 (catalyst)


def test_clamps_to_100():
    news = {"catalyst": True, "catalyst_type": "", "sentiment": "pos", "summary": ""}
    ctx = {"regime": "risk_on", "note": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 95}, news, NEUTRAL_RISK, ctx, CAPS)
    assert out["final_score"] == 100   # 95 + 15 + 5 -> clamped


def test_negative_news_and_risk_off():
    news = {"catalyst": False, "catalyst_type": "", "sentiment": "neg", "summary": ""}
    ctx = {"regime": "risk_off", "note": ""}
    out = adjudicator.adjudicate({"ticker": "X", "score": 50}, news, NEUTRAL_RISK, ctx, CAPS)
    assert out["final_score"] == 35   # 50 - 10 (neg news) - 5 (risk-off)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_adjudicator.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.adjudicator'`)

- [ ] **Step 3: Write `src/adjudicator.py`**

```python
def adjudicate(candidate: dict, news: dict, risk: dict, context: dict, caps: dict) -> dict:
    """Combine the deterministic score with agent verdicts. Pure function.

    Veto wins absolutely. All boosts/demotes are fixed caps. Final score is clamped 0-100.
    """
    ticker = candidate["ticker"]
    base = float(candidate["score"])
    regime = context.get("regime", "neutral")

    if risk.get("veto"):
        return {
            "ticker": ticker,
            "base_score": base,
            "final_score": base,
            "vetoed": True,
            "veto_reason": risk.get("reason", ""),
            "news": news,
            "risk": risk,
            "regime": regime,
            "adjustments": [],
        }

    final = base
    adjustments = []

    level = risk.get("risk_level", "low")
    if level == "high":
        final -= caps["risk_high"]
        adjustments.append(f"-{caps['risk_high']:.0f} high risk")
    elif level == "medium":
        final -= caps["risk_medium"]
        adjustments.append(f"-{caps['risk_medium']:.0f} medium risk")

    if news.get("catalyst"):
        final += caps["catalyst"]
        adjustments.append(f"+{caps['catalyst']:.0f} catalyst")
    if news.get("sentiment") == "neg":
        final -= caps["news_negative"]
        adjustments.append(f"-{caps['news_negative']:.0f} negative news")

    if regime == "risk_off":
        final -= caps["regime"]
        adjustments.append(f"-{caps['regime']:.0f} risk-off market")
    elif regime == "risk_on":
        final += caps["regime"]
        adjustments.append(f"+{caps['regime']:.0f} risk-on market")

    final = max(0.0, min(100.0, final))

    return {
        "ticker": ticker,
        "base_score": base,
        "final_score": final,
        "vetoed": False,
        "veto_reason": "",
        "news": news,
        "risk": risk,
        "regime": regime,
        "adjustments": adjustments,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_adjudicator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/adjudicator.py tests/test_adjudicator.py
git commit -m "feat: rules-based adjudicator (capped boosts/demotes + veto)"
```

---

## Task 7: Briefing render + email (`src/briefing.py`)

**Files:**
- Create: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_briefing.py`

```python
from src import briefing
from tests.fakes import FakeSMTP


def _adjudicated(ticker, final, base, summary, risk_level, reason, adjustments):
    return {
        "ticker": ticker, "base_score": base, "final_score": final,
        "vetoed": False, "veto_reason": "",
        "news": {"summary": summary},
        "risk": {"risk_level": risk_level, "reason": reason},
        "regime": "risk_on", "adjustments": adjustments,
    }


def test_render_briefing_orders_and_shows_sections():
    ranked = [
        _adjudicated("HI", 88, 80, "new deal", "low", "no flags", ["+15 catalyst"]),
        _adjudicated("LO", 60, 65, "no catalyst", "medium", "earnings soon", ["-8 medium risk"]),
    ]
    vetoed = [{"ticker": "BAD", "veto_reason": "fraud probe"}]
    others = [{"ticker": "MEH", "score": 40}]
    excluded = [{"ticker": "PENNY", "reason": "price below floor"}]

    text = briefing.render_briefing(ranked, vetoed, others, excluded,
                                    "2026-06-08", "risk_on", "Market upbeat.")

    assert "2026-06-08" in text
    assert text.index("HI") < text.index("LO")     # ranked order preserved
    assert "fraud probe" in text                    # veto shown
    assert "MEH" in text                            # others shown
    assert "PENNY" in text                          # excluded shown
    assert "not financial advice" in text.lower()


def test_send_email_logs_in_and_sends():
    fake = FakeSMTP()
    briefing.send_email(
        "Subject Line", "Body text",
        host="smtp.test", port=465,
        user="me@test.com", password="pw", to_addr="you@test.com",
        smtp_factory=lambda: fake,
    )
    assert fake.logged_in == ("me@test.com", "pw")
    assert fake.sent_message["Subject"] == "Subject Line"
    assert fake.sent_message["To"] == "you@test.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.briefing'`)

- [ ] **Step 3: Write `src/briefing.py`**

```python
from email.message import EmailMessage


def render_briefing(ranked, vetoed, others, excluded, date_str, regime, regime_note) -> str:
    """Render the enriched daily briefing (Phase 2). `ranked` is pre-sorted by final_score."""
    L = [
        f"# Stock Advisor — {date_str}",
        "",
        f"**Market regime:** {regime} — {regime_note}",
        "",
        "## Top candidates",
    ]
    if not ranked:
        L.append("_No candidates today._")
    for r in ranked:
        adj = "  ".join(r["adjustments"]) or "no adjustments"
        L.append(f"- **{r['ticker']}**: {r['final_score']:.0f}/100 (base {r['base_score']:.0f})")
        L.append(f"    - 📰 {r['news']['summary']}")
        L.append(f"    - 🚩 risk {r['risk']['risk_level']}: {r['risk']['reason']}")
        L.append(f"    - adj: {adj}")

    if vetoed:
        L.append("")
        L.append("## ⛔ Vetoed (do not buy)")
        for r in vetoed:
            L.append(f"- {r['ticker']}: {r['veto_reason']}")

    if others:
        L.append("")
        L.append("## Other scored (below shortlist)")
        for o in others:
            L.append(f"- {o['ticker']}: {o['score']:.0f}/100")

    if excluded:
        L.append("")
        L.append("## Excluded (hard filters)")
        for e in excluded:
            L.append(f"- {e['ticker']}: {e['reason']}")

    L.append("")
    L.append("_Information only — not financial advice._")
    return "\n".join(L) + "\n"


def send_email(subject, body, *, host, port, user, password, to_addr, smtp_factory=None) -> None:
    """Send the briefing via SMTP. `smtp_factory` is injectable for testing."""
    if smtp_factory is None:
        import smtplib
        def smtp_factory():
            return smtplib.SMTP_SSL(host, port)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    with smtp_factory() as server:
        server.login(user, password)
        server.send_message(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_briefing.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add src/briefing.py tests/test_briefing.py
git commit -m "feat: enriched briefing renderer + injectable email send"
```

---

## Task 8: Wire it together (`src/main.py`) + real run

**Files:**
- Modify: `src/main.py` (full replacement below)

- [ ] **Step 1: Replace `src/main.py` with the Phase 2 pipeline**

```python
import datetime as dt
import os
from pathlib import Path

from src import config, data, scoring, news, agents, adjudicator, briefing, report

ROOT = Path(__file__).resolve().parent.parent


def _build_market_summary(scored: list) -> str:
    cands = [s for s in scored if not s["excluded"]]
    if not cands:
        return "No qualifying stocks today."
    avg = sum(s["score"] for s in cands) / len(cands)
    up = sum(1 for s in cands if s["components"]["trend"] >= 1.0)
    return (f"{up}/{len(cands)} watchlist names in a clear uptrend; "
            f"average momentum score {avg:.0f}/100.")


def run() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    wl = config.load_watchlist()
    weights = config.load_weights()
    settings = wl["settings"]
    lookback = settings.get("lookback_days", 200)
    shortlist_size = settings.get("shortlist_size", 8)

    data_dir = ROOT / "data"
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = dt.date.today().isoformat()

    scored = []
    for ticker in wl["tickers"]:
        df = data.fetch_history(ticker, lookback)
        ok, reason = data.validate(df, ticker)
        if ok:
            data.save_cache(df, ticker, data_dir)
        else:
            df = data.load_cache(ticker, data_dir)
            cache_ok, _ = data.validate(df, ticker) if df is not None else (False, "")
            if not cache_ok:
                scored.append({"ticker": ticker, "excluded": True,
                               "reason": f"{reason} (no valid cache)"})
                continue
        result = scoring.score_ticker(df, ticker, weights, settings)
        result["_df"] = df if not result["excluded"] else None
        scored.append(result)

    # Graceful fallback: no API key -> deterministic-only report (Phase 1 behavior)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        clean = [{k: v for k, v in s.items() if k != "_df"} for s in scored]
        text = report.render_report(clean, date_str)
        (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
        print(text)
        print("\n[AI agents disabled: no ANTHROPIC_API_KEY in .env]")
        return text

    from src import llm
    client = llm.AnthropicClient()
    caps = config.load_adjudicator()

    cands = sorted((s for s in scored if not s["excluded"]),
                   key=lambda s: s["score"], reverse=True)
    shortlist = cands[:shortlist_size]
    others = [{"ticker": s["ticker"], "score": s["score"]} for s in cands[shortlist_size:]]
    excluded = [{"ticker": s["ticker"], "reason": s["reason"]}
                for s in scored if s["excluded"]]

    context = agents.context_agent(client, _build_market_summary(scored))

    ranked, vetoed = [], []
    for s in shortlist:
        headlines = news.get_headlines(s["ticker"])
        recent_closes = list(s["_df"]["Close"].tail(10))
        nv = agents.news_agent(client, s["ticker"], headlines)
        rv = agents.risk_agent(client, s["ticker"], recent_closes, headlines)
        adjd = adjudicator.adjudicate(
            {"ticker": s["ticker"], "score": s["score"]}, nv, rv, context, caps
        )
        (vetoed if adjd["vetoed"] else ranked).append(adjd)
    ranked.sort(key=lambda r: r["final_score"], reverse=True)

    text = briefing.render_briefing(
        ranked, vetoed, others, excluded, date_str, context["regime"], context["note"]
    )
    (reports_dir / f"{date_str}.md").write_text(text, encoding="utf-8")
    print(text)

    # Optional email
    if all(os.environ.get(k) for k in ("EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_TO")):
        try:
            briefing.send_email(
                f"Stock Advisor — {date_str}", text,
                host=os.environ.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(os.environ.get("EMAIL_PORT", "465")),
                user=os.environ["EMAIL_USER"],
                password=os.environ["EMAIL_PASSWORD"],
                to_addr=os.environ["EMAIL_TO"],
            )
            print("[briefing emailed]")
        except Exception as e:
            print(f"[email failed: {e}]")

    return text


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the full test suite (no network, no API)**

Run: `& .\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all Phase 1 + Phase 2 tests green)

- [ ] **Step 3: Verify graceful no-key run still works**

Run: `& .\.venv\Scripts\python.exe -m src.main`
Expected: prints the deterministic ranked report plus `[AI agents disabled: no ANTHROPIC_API_KEY in .env]`. Confirms the pipeline still works with zero AI cost.

- [ ] **Step 4: Commit**

```powershell
git add src/main.py
git commit -m "feat: wire AI crew + adjudicator + briefing into the pipeline"
```

- [ ] **Step 5: USER SETUP (walk through together) — enable the real AI run**

1. Create an Anthropic API key at https://console.anthropic.com.
2. In Console → Settings → Limits, **set a $5/month spend limit**.
3. Copy `.env.example` to `.env` and paste the key into `ANTHROPIC_API_KEY=`.
   ```powershell
   Copy-Item .env.example .env
   ```
4. (Optional email) create a Gmail App Password and fill `EMAIL_USER` / `EMAIL_PASSWORD` / `EMAIL_TO`.

- [ ] **Step 6: Real run with agents** (costs a few cents; only after Step 5)

Run: `& .\.venv\Scripts\python.exe -m src.main`
Expected: an enriched briefing with a market-regime line, top candidates each showing a 📰 news note, 🚩 risk note, and `adj:` line, plus any vetoed/other/excluded sections. Saved to `reports/<today>.md`. If email is configured, also prints `[briefing emailed]`.

- [ ] **Step 7: Commit any final fixes** (only if Step 6 surfaced a real issue)

```powershell
git add -A
git commit -m "fix: phase 2 real-run adjustments"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Phase 2 scope):**
- News/Risk/Context agents on Haiku with structured contracts + neutral fallback → Task 3 ✓
- Real Claude client → Task 4 ✓; news source = yfinance → Task 5 ✓
- Rules adjudicator: capped boosts/demotes, veto wins, clamp → Task 6 ✓ (caps in config → Task 1 ✓)
- Enriched briefing with reasoning, vetoed/excluded sections, disclaimer → Task 7 ✓
- Email delivery (Gmail/SMTP), optional + graceful → Task 7 + Task 8 ✓
- Graceful failure (no key → deterministic-only; agent errors → neutral; email failure → notice) → Tasks 3, 8 ✓
- $5/month cap + API key + Gmail app password as guided user setup → Task 8 Step 5 ✓
- Deferred to Phase 3 (not in this plan): positions/exits (sell side), backtesting, Task Scheduler automation.

**Type consistency:** agent outputs (`news`/`risk`/`context` dicts) match the keys the adjudicator reads (`catalyst`, `sentiment`, `risk_level`, `veto`, `reason`, `regime`); adjudicated dict keys (`ticker`, `base_score`, `final_score`, `vetoed`, `veto_reason`, `news`, `risk`, `adjustments`) match what `render_briefing` reads. `client.complete(system, user)` is the single interface used by all agents and provided by both `AnthropicClient` and the fakes. `config.load_adjudicator` caps keys (`catalyst`, `news_negative`, `risk_high`, `risk_medium`, `regime`) match the adjudicator's lookups. Consistent. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; every run step has an exact command + expected result. ✓

---

## What's next (not part of this plan)
**Phase 3 — sell side + backtesting:** `positions.yaml`, exit signals (stop-loss/take-profit/trend-break) shown atop the briefing, and historical replay of the engine to measure win rate vs. buy-and-hold. Then: Task Scheduler automation for a hands-off morning run.
