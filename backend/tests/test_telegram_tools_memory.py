# ====================================================================
# JARVIS OMEGA — hands + memory tests (2026-11-11)
# ====================================================================
"""
Sir's order: "Give him 2 and 3 and make it the best" — (2) real tool
use so the Telegram brain can DO things, and (3) memory like Muse's.

* The brain now injects the vault's FACTS (not just rules/lessons),
  and the Telegram brain gets the vault at all (it never did before —
  only the default prompt carried it).
* After a free-chat turn, durable facts are pulled out and saved to
  the vault automatically (telegram_memory).
* The Telegram brain calls real tools (telegram_tools) through a
  Groq function-calling loop (get_response_with_tools).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.services import dm_store

# --------------------------------------------------------------------
# Vault facts
# --------------------------------------------------------------------

def test_vault_facts(monkeypatch, tmp_path):
    from backend.services.dm_store import JsonStore
    from backend.services.obsidian_vault import ObsidianVault

    store = JsonStore("obsidian_vault.json")
    store._path = tmp_path / "vault.json"
    store._loaded = False
    store._data = {}
    vault = ObsidianVault(store=store)
    assert vault.list_facts() == []
    assert vault.facts_text() == ""
    assert vault.remember_fact("Rayyan prefers voice notes", source="test")
    assert vault.list_facts() == ["Rayyan prefers voice notes"]
    assert vault.facts_text() == "- Rayyan prefers voice notes"
    # Exact duplicates are not added twice.
    vault.remember_fact("Rayyan prefers voice notes", source="test")
    assert vault.list_facts() == ["Rayyan prefers voice notes"]


def test_dm_prompt_includes_vault_facts(monkeypatch, tmp_path):
    from backend.services.dm_llm import _messages
    from backend.services.dm_store import JsonStore
    from backend.services.obsidian_vault import ObsidianVault

    store = JsonStore("obsidian_vault.json")
    store._path = tmp_path / "vault.json"
    store._loaded = False
    store._data = {}
    vault = ObsidianVault(store=store)
    vault.remember_fact("Rayyan prefers voice notes", source="test")
    with patch("backend.services.dm_llm.obsidian_vault", vault):
        messages = _messages("Omar", "hello", first_reply=True)
    assert "Rayyan prefers voice notes" in messages[0]["content"]


def test_chat_prompt_includes_vault_facts(monkeypatch, tmp_path):
    """The Telegram brain gets the vault too (it never did before)."""
    from backend.services.dm_store import JsonStore
    from backend.services.llm_service import llm_service
    from backend.services.obsidian_vault import ObsidianVault

    store = JsonStore("obsidian_vault.json")
    store._path = tmp_path / "vault.json"
    store._loaded = False
    store._data = {}
    vault = ObsidianVault(store=store)
    vault.remember_fact("Rayyan prefers voice notes", source="test")
    with patch("backend.services.obsidian_vault.vault", vault):
        prompt = llm_service._build_default_system_prompt()
    assert "Rayyan prefers voice notes" in prompt


# --------------------------------------------------------------------
# Auto-memory
# --------------------------------------------------------------------

def _groq_fact_response(facts_text: str):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": facts_text}}]},
    )


@pytest.mark.asyncio
async def test_extract_facts_saves_durable_only(monkeypatch):
    from backend.services.telegram_memory import extract_facts

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(return_value=_groq_fact_response(
            "Rayyan prefers voice notes\nRayyan is building a Roblox game"
        )),
    ):
        facts = await extract_facts(
            "I prefer voice notes and I'm building a Roblox game",
            "Got it, sir.",
        )
    assert facts == [
        "Rayyan prefers voice notes",
        "Rayyan is building a Roblox game",
    ]


@pytest.mark.asyncio
async def test_extract_facts_nothing_when_trivial(monkeypatch):
    from backend.services.telegram_memory import extract_facts

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        assert await extract_facts("hi", "Hello sir.") == []
        assert await extract_facts("ok", "Sure.") == []
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_extract_facts_nothing_response(monkeypatch):
    from backend.services.telegram_memory import extract_facts

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(return_value=_groq_fact_response("NOTHING")),
    ):
        assert await extract_facts("how is the weather?", "Sunny.") == []


@pytest.mark.asyncio
async def test_auto_save_facts_to_vault(monkeypatch, tmp_path):
    from backend.services.dm_store import JsonStore
    from backend.services.obsidian_vault import ObsidianVault
    from backend.services.telegram_memory import auto_save_facts

    store = JsonStore("obsidian_vault.json")
    store._path = tmp_path / "vault.json"
    store._loaded = False
    store._data = {}
    vault = ObsidianVault(store=store)
    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    with (
        patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(return_value=_groq_fact_response(
                "Rayyan prefers voice notes"
            )),
        ),
        patch("backend.services.telegram_memory.obsidian_vault", vault),
    ):
        assert await auto_save_facts("I prefer voice notes", "Got it.") == 1
    assert vault.list_facts() == ["Rayyan prefers voice notes"]


# --------------------------------------------------------------------
# Tool loop
# --------------------------------------------------------------------

def _groq_tool_call_response(name: str, args: dict, call_id: str = "call_1"):
    return httpx.Response(
        200,
        json={"choices": [{"message": {
            "content": "",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args),
                },
            }],
        }}]},
    )


def _groq_text_response(text: str):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": text}}]},
    )


@pytest.mark.asyncio
async def test_tool_loop_calls_tool_and_answers(monkeypatch):
    """The model calls a tool, gets the result, and answers from it."""
    from backend.services.llm_service import llm_service
    from backend.tools.registry import RiskTier, Tool

    async def fake_status() -> str:
        return "DM responder is on. Connected: Instagram."

    status_tool = Tool(
        name="telegram.get_status",
        description="Status.",
        func=fake_status,
        parameters={"type": "object", "properties": {}},
        risk_tier=RiskTier.TIER_0_OBSERVE,
        category="telegram",
    )
    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    responses = [
        _groq_tool_call_response("telegram.get_status", {}),
        _groq_text_response("The responder is on and Instagram is connected."),
    ]
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=responses),
    ) as mock_post:
        reply = await llm_service.get_response_with_tools(
            "is the responder on?",
            tools=[status_tool],
        )
    assert reply == "The responder is on and Instagram is connected."
    assert mock_post.call_count == 2
    # The second call carried the tool result back to the model.
    second_payload = mock_post.call_args_list[1].kwargs["json"]
    tool_msgs = [m for m in second_payload["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "responder is on" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_tool_loop_unknown_tool_is_skipped(monkeypatch):
    """A tool call for a tool that does not exist is not executed."""
    from backend.services.llm_service import llm_service
    from backend.tools.registry import RiskTier, Tool

    async def fake_status() -> str:
        return "ok"

    status_tool = Tool(
        name="telegram.get_status",
        description="Status.",
        func=fake_status,
        parameters={"type": "object", "properties": {}},
        risk_tier=RiskTier.TIER_0_OBSERVE,
        category="telegram",
    )
    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    responses = [
        _groq_tool_call_response("telegram.delete_everything", {}),
        _groq_text_response("That tool is not available."),
    ]
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=responses),
    ):
        reply = await llm_service.get_response_with_tools(
            "delete everything",
            tools=[status_tool],
        )
    assert reply == "That tool is not available."


@pytest.mark.asyncio
async def test_tool_loop_falls_back_to_plain_brain(monkeypatch):
    """When the tool call fails, Sir still gets a plain text answer."""
    from backend.services.llm_service import llm_service
    from backend.tools.registry import RiskTier, Tool

    async def fake_status() -> str:
        return "ok"

    status_tool = Tool(
        name="telegram.get_status",
        description="Status.",
        func=fake_status,
        parameters={"type": "object", "properties": {}},
        risk_tier=RiskTier.TIER_0_OBSERVE,
        category="telegram",
    )
    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-key")
    with (
        patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("down")),
        ),
        patch.object(
            llm_service, "get_response",
            new=AsyncMock(return_value="plain answer"),
        ) as mock_plain,
    ):
        reply = await llm_service.get_response_with_tools(
            "hello", tools=[status_tool]
        )
    assert reply == "plain answer"
    mock_plain.assert_called_once()


# --------------------------------------------------------------------
# Telegram tools
# --------------------------------------------------------------------

def test_telegram_tools_curated():
    """The Telegram tool set is small and has no dangerous tools."""
    from backend.services.telegram_tools import telegram_tools

    tools = telegram_tools()
    names = [t.name for t in tools]
    assert len(tools) == 11
    assert all(n.startswith("telegram.") for n in names)
    assert "telegram.send_dm" in names
    assert "telegram.set_reminder" in names
    assert "telegram.send_briefing" in names
    assert "telegram.web_search" in names
    # No shell, no code execution, no deleting, no payments.
    assert not any("shell" in n or "exec" in n or "delete" in n for n in names)
    # Every tool renders an OpenAI schema the model can call.
    for t in tools:
        schema = t.to_openai_schema()
        assert schema["function"]["name"] == t.name
        assert "parameters" in schema["function"]


@pytest.mark.asyncio
async def test_tool_lookup_contact(monkeypatch, tmp_path):
    from backend.services import dm_store
    from backend.services.telegram_tools import telegram_tools

    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    dm_store.contacts.set("Omar", {"phone": "+962700000000", "instagram": "omar_x"})
    tools = {t.name: t for t in telegram_tools()}
    assert await tools["telegram.lookup_contact"](name="Omar") == (
        "Omar — phone: +962700000000, Instagram: omar_x"
    )
    assert "no saved contact" in await tools["telegram.lookup_contact"](name="Zaid")


@pytest.mark.asyncio
async def test_tool_set_reminder_bad_time():
    from backend.services.telegram_tools import telegram_tools

    tools = {t.name: t for t in telegram_tools()}
    reply = await tools["telegram.set_reminder"](
        text="call Omar", when="sometime-ish"
    )
    assert "could not understand the time" in reply.lower()


# --------------------------------------------------------------------
# Webhook uses the tool loop
# --------------------------------------------------------------------

def _telegram_app():
    test_app = FastAPI()
    test_app.include_router(router_telegram.router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


@pytest.mark.asyncio
async def test_webhook_free_chat_uses_tool_loop(monkeypatch, tmp_path):
    """Free chat goes through the tool loop, not the plain brain."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    monkeypatch.setattr(dm_store.telegram_history, "_path", tmp_path / "telegram_history.json")
    monkeypatch.setattr(dm_store.telegram_history, "_loaded", False)
    monkeypatch.setattr(dm_store.telegram_history, "_data", {})
    monkeypatch.setattr(dm_store.briefing, "_path", tmp_path / "briefing.json")
    monkeypatch.setattr(dm_store.briefing, "_loaded", False)
    monkeypatch.setattr(dm_store.briefing, "_data", {})
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
        patch("backend.services.llm_service.llm_service") as mock_llm,
    ):
        mock_llm.get_response_with_tools = AsyncMock(return_value="done, sir.")
        mock_llm.get_response = AsyncMock(return_value="plain brain")
        assert _webhook_post("what is the capital of France?", update_id=1).status_code == 200
    mock_llm.get_response_with_tools.assert_called_once()
    mock_llm.get_response.assert_not_called()
    _, kwargs = mock_llm.get_response_with_tools.call_args
    tool_names = [t.name for t in kwargs["tools"]]
    assert "telegram.send_dm" in tool_names
    assert "telegram.set_reminder" in tool_names
    assert mock_send.call_args.args[0] == "done, sir."
