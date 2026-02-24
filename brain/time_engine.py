from datetime import datetime, timezone, timedelta
from config import MORNING_START, AFTERNOON_START, EVENING_START, NIGHT_START

_TZ = {
    "UTC":0,"GMT":0,"UTC+3":3,"America/New_York":-5,"America/Chicago":-6,
    "America/Denver":-7,"America/Los_Angeles":-8,"America/Sao_Paulo":-3,
    "Europe/London":0,"Europe/Paris":1,"Europe/Berlin":1,"Europe/Moscow":3,
    "Europe/Istanbul":3,"Asia/Dubai":4,"Asia/Karachi":5,"Asia/Kolkata":5,
    "Asia/Dhaka":6,"Asia/Bangkok":7,"Asia/Singapore":8,"Asia/Shanghai":8,
    "Asia/Tokyo":9,"Asia/Seoul":9,"Australia/Sydney":10,"Africa/Cairo":2,
    "Africa/Nairobi":3,"Asia/Riyadh":3,"Asia/Amman":2,"Asia/Beirut":2,
}

def _now(tz="UTC+3"):
    return datetime.now(timezone(timedelta(hours=_TZ.get(tz, 3))))

def get_greeting(tz="UTC+3"):
    h = _now(tz).hour
    if MORNING_START <= h < AFTERNOON_START: return "Good morning"
    if AFTERNOON_START <= h < EVENING_START: return "Good afternoon"
    if EVENING_START <= h < NIGHT_START:     return "Good evening"
    return "Good night"

def get_time_info(tz="UTC"):
    n = _now(tz)
    return {
        "now_str" : n.strftime("%A, %B %d %Y at %I:%M %p"),
        "date_str": n.strftime("%B %d, %Y"),
        "time_str": n.strftime("%I:%M %p"),
        "weekday" : n.strftime("%A"),
        "timezone": tz,
        "hour"    : n.hour,
        "greeting": get_greeting(tz),
    }

def format_response(tz="UTC"):
    i = get_time_info(tz)
    return f"It is currently **{i['time_str']}** on {i['now_str']} ({i['timezone']})."
