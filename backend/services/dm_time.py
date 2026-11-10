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


# A bare clock: "5pm" / "5:30pm" / "17:00" / "8pm" (with or without "at").
_CLOCK_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)


def _clock_to_time(hour: int, minute: int, ampm: str | None, fallback_ampm: str | None) -> tuple[int, int]:
    """Resolve a clock to 24-hour (hour, minute). A clock with no am/pm
    inherits the other clock's am/pm when there is one."""
    use_ampm = (ampm or fallback_ampm or "").lower()
    if use_ampm == "pm" and hour < 12:
        hour += 12
    if use_ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def parse_time_window(
    text: str, now: datetime | None = None
) -> tuple[datetime | None, datetime | None] | None:
    """Parse a time window like \"Friday 5pm-8pm\" or \"from 5pm to 8pm\".

    Returns (start, end) datetimes, or (start, None) when only a start
    was given, or None when no day/time could be understood. The day
    comes from parse_time (weekday / tomorrow / today); the clocks come
    from the bare-clock matches in the text.
    """
    now = now or datetime.now(_AMMAN)
    lowered = (text or "").lower()
    day_dt = parse_time(text, now)
    clocks = []
    for m in _CLOCK_RE.finditer(text or ""):
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        has_colon = ":" in m.group(0)
        if ampm or has_colon:
            clocks.append((hour, minute, (ampm or "").lower() or None))
    if not day_dt:
        # No day word and no "at" clock ("from 5pm to 8pm") — today.
        if not clocks:
            return None
        day_dt = now
    if not clocks:
        return (day_dt, None)
    # The other clock's am/pm is the fallback for a bare clock.
    other_ampm = next((c[2] for c in clocks if c[2]), None)
    start_h, start_m = _clock_to_time(clocks[0][0], clocks[0][1], clocks[0][2], other_ampm)
    start = day_dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if len(clocks) < 2:
        end = None
    else:
        end_h, end_m = _clock_to_time(clocks[1][0], clocks[1][1], clocks[1][2], other_ampm)
        end = day_dt.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if end <= start:
            # "11pm-2am" crosses midnight.
            end = end + timedelta(days=1)
    # "Friday 5pm-8pm" said on a Friday: parse_time pushes a bare weekday
    # to next week, but when the start is still ahead today, it means today.
    weekday = next((num for name, num in _WEEKDAYS.items() if name in lowered), None)
    if (
        weekday is not None
        and weekday == now.weekday()
        and start.date() != now.date()
        and start - timedelta(days=7) > now
    ):
        start = start - timedelta(days=7)
        if end:
            end = end - timedelta(days=7)
    return (start, end)
