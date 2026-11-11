# ====================================================================
# JARVIS OMEGA — model switch tests (2026-11-11)
# ====================================================================
"""
Sir's order: "add a new command to switch between the models" and get
a better free model. /model switches the brain between groq-120b,
groq-20b, gemini and deepseek (OpenRouter free). The choice is stored
in a Turso-backed store and read on every call, so it takes effect
immediately. A model whose key is missing is skipped and the brain
falls through to the next one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import router_telegram
from backend.services import dm_store


def _fresh_model_store(monkeypatch, tmp_path):
    monkeypatch.setattr(dm_store.model_settings, "_path", tmp_path / "model_settings.json")
    monkeypatch.setattr(dm_store.model_settings, "_loaded", False)
    monkeypatch.setattr(dm_store.model_settings, "_data", {})


def test_model_default_is_groq_120b(monkeypatch, tmp_path):
    from backend.services.model_settings import get_active_model

    _fresh_model_store(monkeypatch, tmp_path)
    assert get_active_model() == "groq-120b"


def test_model_switch_round_trip(monkeypatch, tmp_path):
    from backend.services.model_settings import get_active_model, set_active_model

    _fresh_model_store(monkeypatch, tmp_path)
    assert set_active_model("gemini") == "gemini"
    assert get_active_model() == "gemini"
    assert set_active_model("deepseek") == "deepseek"
    assert get_active_model() == "deepseek"
    assert set_active_model("groq-20b") == "groq-20b"
    assert get_active_model() == "groq-20b"


def test_model_switch_rejects_unknown(monkeypatch, tmp_path):
    from backend.services.model_settings import get_active_model, set_active_model

    _fresh_model_store(monkeypatch, tmp_path)
    assert set_active_model("gpt-5") is None
    assert set_active_model("") is None
    assert get_active_model() == "groq-120b"


def test_model_list_text(monkeypatch, tmp_path):
    from backend.services.model_settings import list_models_text, set_active_model

    _fresh_model_store(monkeypatch, tmp_path)
    set_active_model("gemini")
    text = list_models_text()
    assert "groq-120b" in text
    assert "gemini" in text
    assert "deepseek" in text
    assert "current" in text


def test_handle_model_command(monkeypatch, tmp_path):
    from backend.routers.router_telegram import _handle_model

    _fresh_model_store(monkeypatch, tmp_path)
    assert "groq-120b" in _handle_model("")
    assert "Brain switched to gemini" in _handle_model("gemini")
    assert "Brain switched to deepseek" in _handle_model("deepseek")
    assert "don't know a model" in _handle_model("gpt-5")


# --------------------------------------------------------------------
# The chat brain routes to the active model
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_response_uses_gemini_first(monkeypatch):
    """Active model gemini: Gemini answers before Groq is even tried."""
    from backend.services.llm_service import llm_service

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-groq")
    monkeypatch.setattr("backend.config.settings.gemini_api_key", "fake-gemini")
    monkeypatch.setattr("backend.config.settings.openrouter_api_key", "")
    with (
        patch(
            "backend.services.model_settings.get_active_model",
            return_value="gemini",
        ),
        patch.object(
            llm_service, "_gemini_reply",
            new=AsyncMock(return_value="Gemini first, sir."),
        ) as mock_gemini,
        patch.object(
            llm_service, "_post_chat",
            new=AsyncMock(return_value=(False, "down", False)),
        ) as mock_groq,
        patch(
            "backend.services.llm_service.web_search_service"
            ".get_ip_location",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.services.memory_service.memory_service"
            ".get_context_for_query",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        reply = await llm_service.get_response("hello")
    assert reply == "Gemini first, sir."
    mock_gemini.assert_called_once()
    mock_groq.assert_not_called()


@pytest.mark.asyncio
async def test_get_response_uses_deepseek_first(monkeypatch):
    """Active model deepseek: OpenRouter DeepSeek R1 answers first."""
    from backend.services.llm_service import llm_service

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-groq")
    monkeypatch.setattr("backend.config.settings.openrouter_api_key", "fake-or")
    with (
        patch(
            "backend.services.model_settings.get_active_model",
            return_value="deepseek",
        ),
        patch.object(
            llm_service, "_openrouter_reply",
            new=AsyncMock(return_value="DeepSeek thinking, sir."),
        ) as mock_or,
        patch.object(
            llm_service, "_post_chat",
            new=AsyncMock(return_value=(False, "down", False)),
        ) as mock_groq,
        patch(
            "backend.services.llm_service.web_search_service"
            ".get_ip_location",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.services.memory_service.memory_service"
            ".get_context_for_query",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        reply = await llm_service.get_response("hello")
    assert reply == "DeepSeek thinking, sir."
    mock_or.assert_called_once()
    assert mock_or.call_args.args[1] == "deepseek/deepseek-r1:free"
    mock_groq.assert_not_called()


@pytest.mark.asyncio
async def test_get_response_falls_through_when_model_key_missing(monkeypatch):
    """Active model gemini but no key: falls through to Groq."""
    from backend.services.llm_service import llm_service

    monkeypatch.setattr("backend.config.settings.groq_api_key", "fake-groq")
    monkeypatch.setattr("backend.config.settings.gemini_api_key", "")
    monkeypatch.setattr("backend.config.settings.openrouter_api_key", "")
    with (
        patch(
            "backend.services.model_settings.get_active_model",
            return_value="gemini",
        ),
        patch.object(
            llm_service, "_post_chat",
            new=AsyncMock(return_value=(True, "Groq answered.", False)),
        ),
        patch(
            "backend.services.llm_service.web_search_service"
            ".get_ip_location",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.services.memory_service.memory_service"
            ".get_context_for_query",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        reply = await llm_service.get_response("hello")
    assert reply == "Groq answered."


# --------------------------------------------------------------------
# The /model command on Telegram
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
async def test_webhook_model_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    _fresh_model_store(monkeypatch, tmp_path)
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
    ):
        assert _webhook_post("/model gemini", update_id=1).status_code == 200
    assert "Brain switched to gemini" in mock_send.call_args.args[0]
    from backend.services.model_settings import get_active_model

    assert get_active_model() == "gemini"


@pytest.mark.asyncio
async def test_webhook_model_plain_words(monkeypatch, tmp_path):
    """'switch to deepseek' in plain words switches the model too."""
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    _fresh_model_store(monkeypatch, tmp_path)
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
    ):
        assert _webhook_post("switch to deepseek", update_id=1).status_code == 200
    assert "Brain switched to deepseek" in mock_send.call_args.args[0]


def test_telegram_tools_include_switch_model():
    """The brain can switch models from free chat too."""
    from backend.services.telegram_tools import telegram_tools

    names = [t.name for t in telegram_tools()]
    assert "telegram.switch_model" in names
