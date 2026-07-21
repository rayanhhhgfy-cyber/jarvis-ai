# ====================================================================
# JARVIS OMEGA — Local Calendar Plugin (ICS files)
# ====================================================================
"""
Phase 10 plugin: read and write local ``.ics`` calendar files. No Google
API needed — works with any calendar app that imports/exports ICS
(Outlook, Apple Calendar, Google Calendar import, Nextcloud, etc.).

The calendar directory defaults to ``./storage/calendar`` and can hold
multiple ICS files (one per calendar).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


def _cal_dir() -> Path:
    p = Path("./storage/calendar")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_libs():
    try:
        import icalendar  # type: ignore
        return icalendar
    except ImportError as e:
        raise RuntimeError("icalendar not installed — add to requirements.txt") from e


def _parse_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


# --------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------

@tool(
    name="calendar.list_calendars",
    description="List ICS files in the local calendar directory.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="calendar",
)
async def calendar_list_calendars() -> Dict[str, Any]:
    files = sorted(_cal_dir().glob("*.ics"))
    return {
        "ok": True,
        "count": len(files),
        "calendars": [f.stem for f in files],
        "dir": str(_cal_dir()),
    }


@tool(
    name="calendar.list_events",
    description="List events from one or all calendars between two dates (ISO 8601). Defaults to next 7 days.",
    parameters={
        "type": "object",
        "properties": {
            "calendar": {"type": "string", "default": "", "description": "Calendar name (filename without .ics). Empty = all."},
            "from": {"type": "string", "description": "ISO 8601 start. Defaults to now."},
            "to": {"type": "string", "description": "ISO 8601 end. Defaults to now+7d."},
            "limit": {"type": "integer", "default": 50},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="calendar",
)
async def calendar_list_events(calendar: str = "", fr: str = "", to: str = "", limit: int = 50) -> Dict[str, Any]:
    try:
        ical = _load_libs()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    try:
        start = datetime.fromisoformat(fr) if fr else datetime.utcnow()
        end = datetime.fromisoformat(to) if to else datetime.utcnow() + timedelta(days=7)
    except ValueError as e:
        return {"ok": False, "error": f"invalid ISO date: {e}"}

    files = [_cal_dir() / f"{calendar}.ics"] if calendar else sorted(_cal_dir().glob("*.ics"))
    events: List[Dict[str, Any]] = []
    for f in files:
        if not f.exists():
            continue
        try:
            cal = ical.Calendar.from_ical(f.read_text(encoding="utf-8"))
        except Exception as parse_err:
            continue
        for comp in cal.walk("VEVENT"):
            dtstart = _parse_dt(comp.get("dtstart").dt if comp.get("dtstart") else None)
            dtend = _parse_dt(comp.get("dtend").dt if comp.get("dtend") else None)
            if dtstart and start <= dtstart <= end:
                events.append({
                    "calendar": f.stem,
                    "uid": str(comp.get("uid", "")),
                    "summary": str(comp.get("summary", "")),
                    "description": str(comp.get("description", "")),
                    "location": str(comp.get("location", "")),
                    "start": dtstart.isoformat() if dtstart else "",
                    "end": dtend.isoformat() if dtend else "",
                })
    events.sort(key=lambda e: e["start"])
    return {
        "ok": True,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "count": len(events[:limit]),
        "events": events[:limit],
    }


@tool(
    name="calendar.add_event",
    description="Add an event to a local ICS calendar (creates the file if missing).",
    parameters={
        "type": "object",
        "properties": {
            "calendar": {"type": "string", "description": "Calendar name (filename without .ics)."},
            "summary": {"type": "string"},
            "start": {"type": "string", "description": "ISO 8601 start."},
            "end": {"type": "string", "description": "ISO 8601 end."},
            "description": {"type": "string", "default": ""},
            "location": {"type": "string", "default": ""},
        },
        "required": ["calendar", "summary", "start", "end"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="calendar",
)
async def calendar_add_event(
    calendar: str, summary: str, start: str, end: str,
    description: str = "", location: str = "",
) -> Dict[str, Any]:
    try:
        ical = _load_libs()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    try:
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(end)
    except ValueError as e:
        return {"ok": False, "error": f"invalid ISO date: {e}"}

    f = _cal_dir() / f"{calendar}.ics"
    if f.exists():
        try:
            cal = ical.Calendar.from_ical(f.read_text(encoding="utf-8"))
        except Exception:
            cal = ical.Calendar()
    else:
        cal = ical.Calendar()

    import uuid as _uuid
    event = ical.Event()
    event.add("uid", str(_uuid.uuid4()))
    event.add("summary", summary)
    event.add("dtstart", dt_start)
    event.add("dtend", dt_end)
    if description:
        event.add("description", description)
    if location:
        event.add("location", location)
    event.add("dtstamp", datetime.utcnow())
    cal.add_component(event)

    f.write_text(cal.to_ical().decode("utf-8"), encoding="utf-8")
    return {
        "ok": True,
        "calendar": calendar,
        "file": str(f),
        "summary": summary,
        "start": start,
        "end": end,
    }


@tool(
    name="calendar.find_free_slot",
    description="Find the next free N-minute slot in a calendar, scanning the next 14 days from a start time.",
    parameters={
        "type": "object",
        "properties": {
            "calendar": {"type": "string"},
            "duration_minutes": {"type": "integer", "default": 30},
            "from": {"type": "string", "description": "ISO 8601. Defaults to now."},
            "working_hours_start": {"type": "integer", "default": 9},
            "working_hours_end": {"type": "integer", "default": 18},
        },
        "required": ["calendar"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="calendar",
)
async def calendar_find_free_slot(
    calendar: str, duration_minutes: int = 30, fr: str = "",
    working_hours_start: int = 9, working_hours_end: int = 18,
) -> Dict[str, Any]:
    try:
        ical = _load_libs()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    start = datetime.fromisoformat(fr) if fr else datetime.utcnow()
    end_window = start + timedelta(days=14)

    busy: List[tuple] = []
    f = _cal_dir() / f"{calendar}.ics"
    if f.exists():
        try:
            cal = ical.Calendar.from_ical(f.read_text(encoding="utf-8"))
            for comp in cal.walk("VEVENT"):
                ds = _parse_dt(comp.get("dtstart").dt if comp.get("dtstart") else None)
                de = _parse_dt(comp.get("dtend").dt if comp.get("dtend") else None)
                if ds and de:
                    busy.append((ds, de))
        except Exception:
            pass
    busy.sort()

    cursor = start
    duration = timedelta(minutes=duration_minutes)
    while cursor < end_window:
        # Skip outside working hours.
        if cursor.hour < working_hours_start:
            cursor = cursor.replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            continue
        if cursor.hour >= working_hours_end:
            cursor = (cursor + timedelta(days=1)).replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            continue
        candidate_end = cursor + duration
        # Skip weekends (simple heuristic).
        if cursor.weekday() >= 5:
            cursor = (cursor + timedelta(days=1)).replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            continue

        clash = any(
            not (candidate_end <= b_start or cursor >= b_end)
            for b_start, b_end in busy
        )
        if not clash and candidate_end.hour <= working_hours_end:
            return {
                "ok": True,
                "calendar": calendar,
                "start": cursor.isoformat(),
                "end": candidate_end.isoformat(),
                "duration_minutes": duration_minutes,
            }
        cursor += timedelta(minutes=15)

    return {"ok": False, "error": "no free slot found in the next 14 days"}


PLUGIN_NAME = "calendar_local"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Local ICS calendar — list, add events, find free slots. No Google API needed."
