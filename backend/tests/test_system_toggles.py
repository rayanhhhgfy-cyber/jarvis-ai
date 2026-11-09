# ====================================================================
# JARVIS OMEGA — System Toggles Tests
# ====================================================================
"""
Tests for backend/services/system_toggles.py (chat-controlled runtime
toggles) and backend/routers/router_toggles.py.

Everything is mocked: no real keys, no network, no scheduler, no DM
accounts. The approval gateway is a fresh ApprovalGateway per test,
driven by a background task that approves / rejects / stays silent.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from backend.approval_gateway import ApprovalGateway
from backend.config import settings
from backend.services import system_toggles
from backend.services.system_toggles import (
    apply_toggle,
    format_state_report,
    get_state,
    parse_toggle_request,
    request_toggle,
    reset_state,
    submit_toggle_request,
)
from shared.models import ChatRequest


class FakeDMResponder:
    """Stand-in for backend.services.dm_responder.dm_responder."""

    def __init__(self) -> None:
        self.running = False
        self.start_calls = 0
        self.stop_calls = 0

    def get_status(self) -> dict:
        return {
            "enabled": settings.dm_responder_enabled,
            "running": self.running,
            "platforms": {
                "messenger": {"connected": False},
                "instagram": {"connected": False},
            },
        }

    async def start(self) -> None:
        self.start_calls += 1
        self.running = True

    async def stop(self) -> None:
        self.stop_calls += 1
        self.running = False


@pytest.fixture(autouse=True)
def _clean_toggle_state(monkeypatch):
    """Baseline state + fakes for every subsystem driver."""
    orig_dm = settings.dm_responder_enabled
    orig_guardrail = settings.guardrail_enabled
    settings.dm_responder_enabled = False
    settings.guardrail_enabled = False
    reset_state()

    import backend.services.dm_responder as dm_mod

    fake_dm = FakeDMResponder()
    monkeypatch.setattr(dm_mod, "dm_responder", fake_dm)
    monkeypatch.setattr(
        system_toggles, "_autopilot_activate", AsyncMock(return_value={"ok": True})
    )
    monkeypatch.setattr(
        system_toggles, "_autopilot_pause", AsyncMock(return_value={"ok": True})
    )
    monkeypatch.setattr(
        system_toggles, "_cancel_scheduler_job", Mock(return_value=True)
    )
    monkeypatch.setattr(
        system_toggles, "_proactive_start", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        system_toggles, "_proactive_stop", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(system_toggles, "_focus_activate", Mock(return_value=None))
    monkeypatch.setattr(
        system_toggles, "_focus_deactivate", Mock(return_value={"active": False})
    )
    yield fake_dm
    reset_state()
    settings.dm_responder_enabled = orig_dm
    settings.guardrail_enabled = orig_guardrail


async def _capture_approve(gw: ApprovalGateway, holder: dict) -> None:
    for _ in range(100):
        pending = gw.get_pending()
        if pending:
            holder["approval_id"] = pending[0].approval_id
            break
        await asyncio.sleep(0.005)
    assert await gw.approve(holder["approval_id"])


# ----------------------------------------------------------------------
# (a) BLOCKED without approval
# ----------------------------------------------------------------------

async def test_toggle_blocked_on_timeout_changes_nothing(_clean_toggle_state):
    gw = ApprovalGateway()
    assert get_state("dm_responder")["enabled"] is False
    result = await request_toggle("dm_responder", True, timeout=0.05, gateway=gw)
    assert result["applied"] is False
    assert result["ok"] is False
    # Nothing applied: fake never started, runtime flag untouched.
    assert _clean_toggle_state.start_calls == 0
    assert settings.dm_responder_enabled is False
    assert get_state("dm_responder")["enabled"] is False


async def test_toggle_blocked_on_rejection_changes_nothing(_clean_toggle_state):
    gw = ApprovalGateway()
    holder: dict = {}

    async def _capture_and_reject() -> None:
        # request_toggle creates the approval inside; wait for it to appear.
        for _ in range(100):
            pending = gw.get_pending()
            if pending:
                holder["approval_id"] = pending[0].approval_id
                break
            await asyncio.sleep(0.005)
        assert await gw.reject(holder["approval_id"], reason="no")

    asyncio.create_task(_capture_and_reject())
    result = await request_toggle("push_notifications", False, timeout=2.0, gateway=gw)
    assert result["applied"] is False
    assert system_toggles.is_notifications_muted() is False
    assert get_state("push_notifications")["enabled"] is True


async def test_toggle_unknown_id_raises():
    with pytest.raises(KeyError):
        await request_toggle("not_a_toggle", True, timeout=0.05, gateway=ApprovalGateway())
    with pytest.raises(KeyError):
        await apply_toggle("not_a_toggle", True)


async def test_toggle_already_in_state_needs_no_approval():
    gw = ApprovalGateway()
    result = await request_toggle("push_notifications", True, timeout=0.05, gateway=gw)
    assert result["applied"] is False
    assert result["already"] is True
    assert gw.get_pending() == []


# ----------------------------------------------------------------------
# (b) APPLIED after approval
# ----------------------------------------------------------------------

async def test_toggle_applied_after_approval_dm_responder(_clean_toggle_state):
    gw = ApprovalGateway()
    holder: dict = {}

    async def _capture_and_approve() -> None:
        for _ in range(100):
            pending = gw.get_pending()
            if pending:
                holder["approval_id"] = pending[0].approval_id
                break
            await asyncio.sleep(0.005)
        assert await gw.approve(holder["approval_id"])

    asyncio.create_task(_capture_and_approve())
    result = await request_toggle("dm_responder", True, timeout=2.0, gateway=gw)
    assert result["applied"] is True
    assert result["enabled"] is True
    assert _clean_toggle_state.start_calls == 1
    assert _clean_toggle_state.running is True
    assert settings.dm_responder_enabled is True
    assert get_state("dm_responder")["enabled"] is True


async def test_toggle_applied_after_approval_mutes_notifications():
    gw = ApprovalGateway()
    holder: dict = {}
    asyncio.create_task(_capture_approve(gw, holder))
    result = await request_toggle("push_notifications", False, timeout=2.0, gateway=gw)
    assert result["applied"] is True
    assert system_toggles.is_notifications_muted() is True
    assert get_state("push_notifications")["enabled"] is False


async def test_autopilot_master_and_single_job():
    gw = ApprovalGateway()
    holder: dict = {}
    asyncio.create_task(_capture_approve(gw, holder))
    result = await request_toggle("autopilot", True, timeout=2.0, gateway=gw)
    assert result["applied"] is True
    assert get_state("autopilot")["enabled"] is True

    # Turning off one job cancels just that job; the master stays on.
    holder.clear()
    asyncio.create_task(_capture_approve(gw, holder))
    result = await request_toggle("autopilot_uptime_check", False, timeout=2.0, gateway=gw)
    assert result["applied"] is True
    assert get_state("autopilot_uptime_check")["enabled"] is False
    assert get_state("autopilot")["enabled"] is True
    assert get_state("autopilot_brand_mention")["enabled"] is True


async def test_submit_toggle_request_is_nonblocking_and_applies_on_approval():
    gw = ApprovalGateway()
    result = await submit_toggle_request(
        "push_notifications", False, timeout=2.0, gateway=gw
    )
    assert result["status"] == "awaiting_approval"
    assert result["approval_id"]
    # Not applied yet — approval is still pending.
    assert system_toggles.is_notifications_muted() is False
    assert await gw.approve(result["approval_id"])
    await asyncio.sleep(0.05)
    assert system_toggles.is_notifications_muted() is True


# ----------------------------------------------------------------------
# (c) STATE REPORT is accurate
# ----------------------------------------------------------------------

async def test_state_report_accurate_after_changes(_clean_toggle_state):
    gw = ApprovalGateway()
    holder: dict = {}
    asyncio.create_task(_capture_approve(gw, holder))
    await request_toggle("dm_responder", True, timeout=2.0, gateway=gw)
    holder.clear()
    asyncio.create_task(_capture_approve(gw, holder))
    await request_toggle("push_notifications", False, timeout=2.0, gateway=gw)

    state = get_state()
    assert state["dm_responder"]["enabled"] is True
    assert state["push_notifications"]["enabled"] is False
    assert state["autopilot"]["enabled"] is False
    assert state["proactive_watcher"]["enabled"] is True
    assert state["focus_mode"]["enabled"] is False
    assert len(state) == len(system_toggles.TOGGLES)

    report = format_state_report(state)
    assert "DM responder: ON" in report
    assert "Push notifications: OFF" in report
    assert "Autopilot (all jobs): OFF" in report
    assert "Proactive watcher: ON" in report


def test_state_report_single_toggle_unknown_raises():
    with pytest.raises(KeyError):
        get_state("not_a_toggle")


# ----------------------------------------------------------------------
# Chat parsing
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,expected",
    [
        ("turn off the DM responder", ("dm_responder", False)),
        ("Turn off the DM responder", ("dm_responder", False)),
        ("please turn on the DM responder", ("dm_responder", True)),
        ("pause autopilot", ("autopilot", False)),
        ("resume autopilot", ("autopilot", True)),
        ("turn off the uptime check", ("autopilot_uptime_check", False)),
        ("disable the brand mention job", ("autopilot_brand_mention", False)),
        ("mute push notifications", ("push_notifications", False)),
        ("unmute notifications", ("push_notifications", True)),
        ("start the proactive watcher", ("proactive_watcher", True)),
        ("turn on focus mode", ("focus_mode", True)),
        ("enable the guardrail", ("guardrail", True)),
    ],
)
def test_parse_toggle_requests(message, expected):
    parsed = parse_toggle_request(message)
    assert parsed is not None
    assert parsed["kind"] == "toggle"
    assert (parsed["toggle_id"], parsed["desired"]) == expected


@pytest.mark.parametrize(
    "message",
    ["what is on?", "what's on?", "show me the status", "list the toggles", "is the DM responder on?"],
)
def test_parse_state_questions(message):
    parsed = parse_toggle_request(message)
    assert parsed is not None
    assert parsed["kind"] == "state"


@pytest.mark.parametrize(
    "message",
    [
        "hello, how are you?",
        "send a notification to Rayyan about the meeting",
        "what did you think of the notifications feature?",
        "the DM responder is interesting, tell me more",
        "turn off the computer",
        "",
    ],
)
def test_parse_ignores_non_toggle_messages(message):
    assert parse_toggle_request(message) is None


# ----------------------------------------------------------------------
# Notification engine honours the mute flag (history still recorded)
# ----------------------------------------------------------------------

async def test_notification_engine_muted_delivers_nothing(tmp_path):
    from backend.notification_engine import NotificationEngine
    from shared.models import Notification

    engine = NotificationEngine(storage_dir=str(tmp_path))
    await engine.initialize()
    assert await engine.send_notification(
        Notification(title="hi", body="there", category="test")
    ) is False  # no subscriptions registered
    assert len(await engine.get_history()) == 1

    system_toggles._notifications_muted = True
    try:
        assert await engine.send_notification(
            Notification(title="hi2", body="there", category="test")
        ) is False
        # Muted delivery still lands in history (audit trail).
        assert len(await engine.get_history()) == 2
    finally:
        system_toggles._notifications_muted = False


# ----------------------------------------------------------------------
# REST router + chat wiring (service-level, no live server)
# ----------------------------------------------------------------------

async def test_router_toggles_list_and_get():
    from backend.routers.router_toggles import get_toggle, list_toggles

    listed = await list_toggles()
    assert set(listed["toggles"]) == set(system_toggles.TOGGLES)
    one = await get_toggle("dm_responder")
    assert one["id"] == "dm_responder"
    with pytest.raises(HTTPException):
        await get_toggle("not_a_toggle")


async def test_chat_state_question_answered_without_llm(monkeypatch):
    import importlib

    router_chat = importlib.import_module("backend.routers.router_chat")

    req = ChatRequest(message="what is on?", conversation_id="test-session")
    result = await router_chat.process_chat(req)
    assert "DM responder" in result["content"]
    assert "ON" in result["content"] or "OFF" in result["content"]
    assert result["conversation_id"] == "test-session"


async def test_chat_toggle_request_goes_through_request_toggle(monkeypatch):
    import importlib

    router_chat = importlib.import_module("backend.routers.router_chat")

    async def _fake_request_toggle(toggle_id, desired, timeout=300.0):
        assert toggle_id == "dm_responder"
        assert desired is False
        return {"applied": True, "label": "DM responder", "enabled": False, "note": ""}

    monkeypatch.setattr(router_chat, "request_toggle", _fake_request_toggle)
    req = ChatRequest(message="turn off the DM responder", conversation_id="test-session")
    result = await router_chat.process_chat(req)
    assert "DM responder is now OFF" in result["content"]
