# ====================================================================
# JARVIS OMEGA — Telegram Bridge Unit Tests
# ====================================================================
"""
Unit tests for the Telegram Bridge and its reply command.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.telegram_app.telegram_bridge import TelegramBridge

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def bridge():
    tb = TelegramBridge()
    tb._bot = MagicMock()
    tb._bot.send_message = AsyncMock()
    return tb

@pytest.mark.anyio
async def test_record_chat(bridge):
    """Test that incoming message metadata is correctly cached."""
    mock_update = MagicMock()
    mock_update.effective_user.first_name = "Alice"
    mock_update.effective_user.last_name = "Smith"
    mock_update.effective_user.username = "alicesmith"
    mock_update.effective_chat.id = 12345
    
    bridge._record_chat(mock_update)
    
    assert bridge._telegram_chats["alice"] == 12345
    assert bridge._telegram_chats["smith"] == 12345
    assert bridge._telegram_chats["alice smith"] == 12345
    assert bridge._telegram_chats["alicesmith"] == 12345
    assert bridge._telegram_chats["@alicesmith"] == 12345

@pytest.mark.anyio
@patch("backend.services.llm_service.llm_service")
async def test_cmd_reply_telegram_direct(mock_llm, bridge):
    """Test the /reply command for direct Telegram routing."""
    # Pre-populate chat ID
    bridge._telegram_chats["bob"] = 67890
    
    mock_update = MagicMock()
    mock_update.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    mock_context.args = ["bob", "I", "am", "busy"]
    
    mock_llm.get_response = AsyncMock(return_value="JARVIS: I am currently occupied.")
    
    # Mock authorize to return True
    with patch.object(bridge, "_authorize", return_value=True):
        await bridge._cmd_reply(mock_update, mock_context)
        
        # Verify LLM was called to polish
        mock_llm.get_response.assert_called_once()
        # Verify message was sent to Telegram bot
        bridge._bot.send_message.assert_called_once_with(chat_id=67890, text="JARVIS: I am currently occupied.")
        # Verify feedback message to Sir
        mock_update.message.reply_text.assert_any_call("✅ Message sent to bob on Telegram:\n\nJARVIS: I am currently occupied.")
