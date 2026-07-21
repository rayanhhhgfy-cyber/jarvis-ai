# ====================================================================
# Phase 10 batch 2 tests: web, email_imap, calendar_local
# ====================================================================
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.tools import get_registry, RiskTier


def test_phase10_batch2_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.web.plugin",
        "plugins.email_imap.plugin",
        "plugins.calendar_local.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    assert "web.wikipedia" in names
    assert "email.list" in names
    assert "calendar.add_event" in names


# --------------------------------------------------------------------
# Web plugin — all read-only
# --------------------------------------------------------------------

def test_web_tools_are_tier_0():
    reg = get_registry()
    for t in reg.all_tools():
        if t.category == "web":
            assert t.risk_tier is RiskTier.TIER_0_OBSERVE, f"{t.name} should be Tier 0"


# --------------------------------------------------------------------
# Email IMAP — credentials-vault gating
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_list_returns_error_when_credentials_missing(monkeypatch):
    import plugins.email_imap.plugin as em
    monkeypatch.setattr(em, "_cred", lambda key: None)
    result = await em.email_list()
    assert result["ok"] is False
    assert "imap" in result["error"].lower()


# --------------------------------------------------------------------
# Calendar — local ICS round-trip
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_add_then_list_round_trip(monkeypatch, tmp_path):
    pytest.importorskip("icalendar")
    import plugins.calendar_local.plugin as cal
    monkeypatch.setattr(cal, "_cal_dir", lambda: tmp_path)

    start = (datetime.utcnow() + timedelta(days=1)).replace(microsecond=0).isoformat()
    end = (datetime.utcnow() + timedelta(days=1, hours=1)).replace(microsecond=0).isoformat()
    add_result = await cal.calendar_add_event(
        calendar="test", summary="Test event",
        start=start, end=end, description="for testing",
    )
    assert add_result["ok"] is True

    list_result = await cal.calendar_list_events(
        calendar="test",
        fr=(datetime.utcnow() - timedelta(hours=1)).isoformat(),
        to=(datetime.utcnow() + timedelta(days=2)).isoformat(),
    )
    assert list_result["ok"] is True
    assert list_result["count"] >= 1
    assert list_result["events"][0]["summary"] == "Test event"


@pytest.mark.asyncio
async def test_calendar_find_free_slot_returns_slot_when_empty(monkeypatch, tmp_path):
    pytest.importorskip("icalendar")
    import plugins.calendar_local.plugin as cal
    monkeypatch.setattr(cal, "_cal_dir", lambda: tmp_path)
    result = await cal.calendar_find_free_slot(calendar="empty", duration_minutes=30)
    assert result["ok"] is True
    assert "start" in result


@pytest.mark.asyncio
async def test_calendar_handles_missing_lib(monkeypatch):
    """If icalendar isn't installed, all tools return a clear error."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "icalendar":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import plugins.calendar_local.plugin as cal
    result = await cal.calendar_list_calendars()
    # list_calendars doesn't need icalendar — it's just file system listing.
    assert result["ok"] is True

    result = await cal.calendar_add_event(
        calendar="x", summary="y",
        start="2030-01-01T10:00:00", end="2030-01-01T11:00:00",
    )
    assert result["ok"] is False
    assert "icalendar" in result["error"]
