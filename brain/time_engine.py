# =============================================================================
# brain/time_engine.py — Time awareness (no zoneinfo, no tzdata needed)
# Uses only Python stdlib datetime — works on Windows Python 3.13+
# =============================================================================

from datetime import datetime, timezone, timedelta
from config import MORNING_START, AFTERNOON_START, EVENING_START, NIGHT_START

_TZ_OFFSETS = {
    "UTC": 0, "GMT": 0,
    "America/New_York": -5, "America/Chicago": -6,
    "America/Denver": -7, "America/Los_Angeles": -8,
    "America/Sao_Paulo": -3, "America/Toronto": -5,
    "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1,
    "Europe/Rome": 1, "Europe/Madrid": 1, "Europe/Amsterdam": 1,
    "Europe/Moscow": 3, "Europe/Istanbul": 3,
    "Asia/Dubai": 4, "Asia/Karachi": 5, "Asia/Kolkata": 5,
    "Asia/Colombo": 5, "Asia/Dhaka": 6, "Asia/Bangkok": 7,
    "Asia/Jakarta": 7, "Asia/Singapore": 8, "Asia/Shanghai": 8,
    "Asia/Hong_Kong": 8, "Asia/Tokyo": 9, "Asia/Seoul": 9,
    "Australia/Sydney": 10, "Australia/Melbourne": 10,
    "Pacific/Auckland": 12, "Africa/Cairo": 2,
    "Africa/Nairobi": 3, "Africa/Lagos": 1,
    "Asia/Riyadh": 3, "Asia/Kuwait": 3, "Asia/Baghdad": 3,
    "Asia/Amman": 2, "Asia/Beirut": 2, "Asia/Jerusalem": 2,
}

def _local_now(timezone_str="UTC"):
    offset_hours = _TZ_OFFSETS.get(timezone_str, 0)
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.now(tz)

def get_greeting(timezone_str="UTC"):
    hour = _local_now(timezone_str).hour
    if MORNING_START <= hour < AFTERNOON_START:
        return "Good morning"
    elif AFTERNOON_START <= hour < EVENING_START:
        return "Good afternoon"
    elif EVENING_START <= hour < NIGHT_START:
        return "Good evening"
    else:
        return "Good night"

def get_time_info(timezone_str="UTC"):
    now = _local_now(timezone_str)
    return {
        "now_str"  : now.strftime("%A, %B %d %Y at %I:%M %p"),
        "date_str" : now.strftime("%B %d, %Y"),
        "time_str" : now.strftime("%I:%M %p"),
        "weekday"  : now.strftime("%A"),
        "timezone" : timezone_str,
        "hour"     : now.hour,
        "greeting" : get_greeting(timezone_str),
    }

def format_response(timezone_str="UTC"):
    info = get_time_info(timezone_str)
    return f"It is currently **{info['time_str']}** on {info['now_str']} ({info['timezone']})."
