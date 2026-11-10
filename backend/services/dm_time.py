# ====================================================================
# JARVIS OMEGA — DM Time Parsing (natural-language times for Sir)
# ====================================================================
"""
Parse the times Sir uses on Telegram: "tomorrow at 5pm", "at 17:00",
"in 2 hours", "in 30 minutes", "Friday at 6pm", "tonight at 9".
Returns a timezone-aware datetime, or None when it cannot be parsed.
All times are in Sir's timezone (Asia/Amman).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_AMMAN = ZoneInfo("Asia/Amman")

# "in 30 minutes" / "in 2 hours" / "in 3 days"
_IN_RE = re.compile(
    r"\bin\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|hrs|day|days)\b",
    re.IGNORECASE,
)
# "at 5pm" / "at 5:30pm" / "at 17:00" / "at 9"
_AT_RE = re.compile(
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)
# "tomorrow" / "tonight" / "today"
_DAY_WORDS = ("tomorrow", "tonight", "today")
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _apply_clock(base: datetime, hour: int, minute: int, ampm: str | None) -> datetime:
    """Set the clock on a date, handling am/pm. 12-hour times roll
    forward: 'at 5pm' when it is already 6pm means tomorrow."""
    if ampm:
        if ampm.lower() == "pm" and hour < 12:
            hour += 12
        if ampm.lower() == "am" and hour == 12:
            hour = 0
    result = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return result


def parse_time(text: str, now: datetime | None = None) -> datetime | None:
    """Parse a time expression from Sir's message. Returns None if unsure."""
    now = now or datetime.now(_AMMAN)
    lowered = (text or "").lower()

    # "in 2 hours" / "in 30 minutes"
    m = _IN_RE.search(lowered)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("min"):
            return now + timedelta(minutes=amount)
        if unit.startswith("hour") or unit.startswith("hr"):
            return now + timedelta(hours=amount)
        if unit.startswith("day"):
            return now + timedelta(days=amount)

    # A weekday name ("Friday at 6pm" / "Friday").
    weekday = None
    for name, num in _WEEKDAYS.items():
        if name in lowered:
            weekday = num
            break

    # A clock ("at 5pm" / "at 17:00").
    m = _AT_RE.search(lowered)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if hour > 23 or minute > 59:
            return None
        base = now
        if weekday is not None:
            # Next occurrence of that weekday (today counts if later).
            days_ahead = (weekday - now.weekday()) % 7
            base = now + timedelta(days=days_ahead)
        elif "tomorrow" in lowered or "tonight" in lowered:
            base = now + timedelta(days=1)
        result = _apply_clock(base, hour, minute, ampm)
        # A bare "at 5pm" in the past means tomorrow.
        if result <= now and weekday is None and "tomorrow" not in lowered and "tonight" not in lowered:
            result = result + timedelta(days=1)
        return result

    # A bare weekday ("Friday") means that day at 18:00.
    if weekday is not None:
        days_ahead = (weekday - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (now + timedelta(days=days_ahead)).replace(
            hour=18, minute=0, second=0, microsecond=0
        )

    # "tomorrow" alone means tomorrow at 09:00.
    if "tomorrow" in lowered:
        return (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
    return None


def describe_time(when: datetime) -> str:
    """A short human description of a parsed time, in Sir's timezone."""
    local = when.astimezone(_AMMAN)
    today = datetime.now(_AMMAN).date()
    if local.date() == today:
        return f"today at {local.strftime('%H:%M')}"
    if local.date() == today + timedelta(days=1):
        return f"tomorrow at {local.strftime('%H:%M')}"
    return local.strftime("%A %H:%M")
