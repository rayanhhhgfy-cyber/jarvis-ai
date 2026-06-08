# ====================================================================
# JARVIS OMEGA — Focus Mode Service Unit Tests
# ====================================================================
"""
Unit tests for the Focus Mode (DND + Auto-Reply + Queue Summary) service.
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from backend.services.focus_mode import FocusModeService

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def focus_service():
    return FocusModeService()


def test_activate_deactivate(focus_service):
    """Test activation, deactivation, and basic status fields."""
    assert focus_service.is_active() is False
    
    # Activate
    focus_service.activate("Working on code", duration_minutes=30, auto_reply=True)
    assert focus_service.is_active() is True
    
    status = focus_service.get_status()
    assert status["active"] is True
    assert status["focus_note"] == "Working on code"
    assert status["auto_reply_enabled"] is True
    assert status["queued_count"] == 0
    assert status["expires_at"] is not None
    assert status["time_remaining_seconds"] > 0
    
    # Deactivate
    result = focus_service.deactivate()
    assert focus_service.is_active() is False
    assert result["active"] is False
    assert result["queued_count"] == 0

def test_auto_expiry(focus_service):
    """Test that Focus Mode automatically expires after the given duration."""
    # Activate with negative duration (expired)
    focus_service.activate("Fast session", duration_minutes=-1)
    assert focus_service.is_active() is False

def test_message_queuing(focus_service):
    """Test that messages are queued only when active, and exclusion list works."""
    assert focus_service.is_active() is False
    focus_service.queue_message("Alice", "Telegram", "Hello!")
    assert len(focus_service._queued_messages) == 0
    
    # Exclude contact
    focus_service.add_exclude_contact("12345")
    assert focus_service.is_excluded("12345") is True
    
    # Remove exclude
    focus_service.remove_exclude_contact("12345")
    assert focus_service.is_excluded("12345") is False
    
    # Activate and queue
    focus_service.activate("Gaming")
    focus_service.queue_message("Bob", "Discord", "Are you online?")
    focus_service.queue_message("Charlie", "Telegram", "Urgent bug!")
    
    status = focus_service.get_status()
    assert status["queued_count"] == 2
    
    # Deactivate and retrieve queued messages
    result = focus_service.deactivate()
    assert result["queued_count"] == 2
    assert result["queued_messages"][0]["sender"] == "Bob"
    assert result["queued_messages"][1]["sender"] == "Charlie"

@pytest.mark.anyio
@patch("backend.services.focus_mode.llm_service")
async def test_auto_reply_generation(mock_llm, focus_service):
    """Test LLM-based auto-reply and fallback mechanisms."""
    mock_llm.get_response = AsyncMock(return_value="JARVIS: Sir is currently gaming.")
    
    # When inactive
    reply_inactive = await focus_service.get_auto_reply("Alice", "Hey")
    assert reply_inactive is None
    
    # Active with auto-reply disabled
    focus_service.activate("Gaming", auto_reply=False)
    reply_disabled = await focus_service.get_auto_reply("Alice", "Hey")
    assert reply_disabled is None
    
    # Active with auto-reply enabled
    focus_service.activate("Gaming", auto_reply=True)
    reply_active = await focus_service.get_auto_reply("Alice", "Hey")
    assert reply_active == "JARVIS: Sir is currently gaming."
    mock_llm.get_response.assert_called_once()
    
    # LLM failure fallback
    mock_llm.get_response.side_effect = Exception("LLM connection error")
    reply_fallback = await focus_service.get_auto_reply("Alice", "Hey")
    assert "JARVIS" in reply_fallback
    assert "occupied" in reply_fallback

@pytest.mark.anyio
@patch("backend.services.focus_mode.llm_service")
async def test_queued_summary_generation(mock_llm, focus_service):
    """Test LLM-based queued message summary generation."""
    mock_llm.get_response = AsyncMock(return_value="Alice asked about the project. Bob asked to play games.")
    
    # Empty queue
    summary_empty = await focus_service.generate_queued_summary()
    assert "No messages" in summary_empty
    
    # Queue messages
    focus_service.activate("Working")
    focus_service.queue_message("Alice", "Telegram", "Project status?")
    focus_service.queue_message("Bob", "Discord", "Play game?")
    
    summary = await focus_service.generate_queued_summary()
    assert summary == "Alice asked about the project. Bob asked to play games."
    mock_llm.get_response.assert_called_once()
    
    # Fallback on LLM error
    mock_llm.get_response.side_effect = Exception("LLM error")
    summary_fallback = await focus_service.generate_queued_summary()
    assert "missed 2 messages" in summary_fallback
    assert "Alice" in summary_fallback
    assert "Bob" in summary_fallback
