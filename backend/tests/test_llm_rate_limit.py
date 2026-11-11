# ====================================================================
# Tests for the Groq free-tier rate-limit fix (2026-11-09).
#
# Groq's free on_demand tier for openai/gpt-oss-120b allows 8,000 TPM.
# A dashboard request used to be ~5,700 input tokens, so the chat died
# after ~3 messages. These tests prove, with a mocked transport and no
# real key or network:
#   1. conversation history sent to the model is capped (last 4 turns),
#   2. a 429 honors Groq's retry-after delay (capped at 30s) before
#      retrying, and
#   3. a rate-limited 120B call falls back to openai/gpt-oss-20b.
# ====================================================================

from __future__ import annotations

import asyncio
import importlib

import pytest

# NOTE: plain `import backend.services.llm_service as ...` binds the
# *instance* (backend/services/__init__.py re-exports `llm_service` as the
# service object), so go through importlib to get the real module.
llm_module = importlib.import_module("backend.services.llm_service")
from backend.services.llm_service import LLMService
from shared.models import MemoryContext


class FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int, body: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = body
        self.headers = headers or {}

    def json(self):
        import json

        return json.loads(self.text)


class FakeClient:
    """httpx.AsyncClient stand-in routing by payload model."""

    def __init__(self, *args, **kwargs):
        self.posts: list[dict] = []
        self._by_model: dict[str, list[FakeResponse]] = {}

    def set_responses(self, model: str, responses: list[FakeResponse]) -> None:
        self._by_model[model] = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "json": json})
        model = (json or {}).get("model", "")
        queue = self._by_model.get(model) or self._by_model.get("*") or []
        if queue:
            return queue.pop(0)
        return FakeResponse(200, '{"choices": [{"message": {"content": "ok"}}]}')


def _ok_response(content: str = "alive") -> FakeResponse:
    return FakeResponse(200, f'{{"choices": [{{"message": {{"content": "{content}"}}}}]}}')


def _rate_limit_response(delay_s: str = "0.1") -> FakeResponse:
    import json

    body = json.dumps(
        {
            "error": {
                "message": (
                    "Rate limit reached for model openai/gpt-oss-120b in "
                    "organization. Limit 8000 tokens per minute. "
                    f"Please try again in {delay_s}s."
                ),
                "type": "rate_limit_exceeded",
            }
        }
    )
    return FakeResponse(429, body)


@pytest.fixture
def service(monkeypatch):
    """LLMService with keys faked, memory/location stubbed, no network."""
    svc = LLMService()
    monkeypatch.setattr(llm_module.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "openrouter_api_key", "")

    class _FakeMemory:
        async def get_context_for_query(self, query):
            return MemoryContext()

    monkeypatch.setattr(llm_module, "memory_service", _FakeMemory())

    async def _no_location():
        return None

    monkeypatch.setattr(
        llm_module.web_search_service, "get_ip_location", _no_location
    )
    return svc


@pytest.fixture
def sleep_recorder(monkeypatch):
    """Record asyncio.sleep delays without actually sleeping."""
    delays: list[float] = []

    async def _fake_sleep(delay: float):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return delays


async def test_history_capped_to_last_four_turns(service, monkeypatch):
    """A 20-turn session sends only the last 4 turns to the model."""
    client = FakeClient()
    client.set_responses("*", [_ok_response()])
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", lambda *a, **k: client)

    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"question {i}"})
        history.append({"role": "assistant", "content": f"answer {i}"})
    # Last turn's user message is huge (e.g. a pasted command output).
    history[-2] = {"role": "user", "content": "x" * 5000}

    reply = await service.get_response("hello there", chat_history=history)
    assert reply == "alive"

    payload = client.posts[0]["json"]
    msgs = payload["messages"]
    # system + last 4 turns (8 msgs) + current user message
    assert len(msgs) == 10
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "hello there"}
    history_msgs = msgs[1:-1]
    assert history_msgs[0]["content"] == "question 16"
    assert history_msgs[-2]["content"].startswith("x" * 100)
    assert all(len(m["content"]) <= 1513 for m in history_msgs)


async def test_429_honors_retry_after_then_succeeds(service, monkeypatch, sleep_recorder):
    """A 429 waits the delay Groq asked for, then retries and succeeds."""
    client = FakeClient()
    client.set_responses(
        "openai/gpt-oss-120b",
        [_rate_limit_response("27.015"), _ok_response("after retry")],
    )
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", lambda *a, **k: client)

    reply = await service.get_response("hello there")
    assert reply == "after retry"
    assert sleep_recorder == [27.015]
    assert len(client.posts) == 2
    assert client.posts[0]["json"]["model"] == "openai/gpt-oss-120b"


async def test_429_retry_after_capped_at_30s(service, monkeypatch, sleep_recorder):
    """A 90s retry-after is capped at 30s, not waited in full."""
    client = FakeClient()
    client.set_responses(
        "openai/gpt-oss-120b",
        [_rate_limit_response("90"), _ok_response()],
    )
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", lambda *a, **k: client)

    reply = await service.get_response("hello there")
    assert reply == "alive"
    assert sleep_recorder == [30.0]


async def test_429_exhausted_falls_back_to_20b(service, monkeypatch, sleep_recorder):
    """120B rate-limited on every attempt -> same request on gpt-oss-20b."""
    client = FakeClient()
    client.set_responses(
        "openai/gpt-oss-120b",
        [_rate_limit_response("0.1")] * 3,
    )
    client.set_responses("openai/gpt-oss-20b", [_ok_response("from 20b")])
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", lambda *a, **k: client)

    reply = await service.get_response("hello there")
    assert reply == "from 20b"
    models = [p["json"]["model"] for p in client.posts]
    assert models.count("openai/gpt-oss-120b") == 3
    assert models[-1] == "openai/gpt-oss-20b"


async def test_413_falls_back_to_20b_without_retrying_120b(service, monkeypatch):
    """413 (request too large) skips 120B retries and goes straight to 20B."""
    client = FakeClient()
    client.set_responses(
        "openai/gpt-oss-120b",
        [FakeResponse(413, '{"error": {"message": "Request too large"}}')],
    )
    client.set_responses("openai/gpt-oss-20b", [_ok_response("from 20b")])
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", lambda *a, **k: client)

    reply = await service.get_response("hello there")
    assert reply == "from 20b"
    models = [p["json"]["model"] for p in client.posts]
    assert models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_memory_context_capped():
    """Long memories are truncated and the whole block is capped."""
    from shared.constants import MemoryCategory
    from shared.models import MemoryContext, MemoryEntry

    def _mem(content: str) -> MemoryEntry:
        return MemoryEntry(content=content, category=MemoryCategory.CONVERSATIONS, source="test")

    ctx = MemoryContext(
        preference_memories=[_mem("p" * 1000)],
        project_memories=[_mem("j" * 1000) for _ in range(5)],
        general_memories=[_mem("g" * 1000) for _ in range(10)],
    )
    text = LLMService()._format_memory_context(ctx)
    assert len(text) <= 2100
    assert "p" * 301 not in text
    assert "…" in text


def test_system_prompt_trimmed_but_persona_intact():
    """The prompt shrank a lot without losing persona or capabilities."""
    prompt = LLMService()._build_default_system_prompt()
    # Was 20,600 chars; the 16,000 cap leaves room for Sir's standing
    # never-invent rule, injected from the vault (~270 chars).
    assert len(prompt) < 16000
    assert len(prompt) // 4 < 4000  # was ~5,150 rough tokens
    for needle in (
        "J.A.R.V.I.S.",
        "NEVER FAKE OUTPUT",
        "<run_os_command>",
        "Sir",
        "سيدي",
        "agency.build_project",
        "zakat_calculator",
        "paper_buy",
        "SECONDARY SIM",
        "zain_cash_qr",
        "autopilot.*",
        "599 TOOLS",
        "You rest. I work. 24/7.",
        "JARVIS NEVER TOUCHES MONEY",
    ):
        assert needle in prompt, needle
