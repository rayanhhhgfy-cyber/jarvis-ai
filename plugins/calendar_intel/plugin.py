# Phase 18: Calendar Intelligence (REAL)
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="calendar.analyze", description="Analyze upcoming events + suggest optimal work blocks.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="calendar_intel")
async def analyze() -> Dict[str, Any]:
    from plugins.calendar_local.plugin import calendar_list_events
    events = await calendar_list_events(fr=datetime.utcnow().isoformat(), to=(datetime.utcnow() + timedelta(days=7)).isoformat())
    if not events.get("ok"): return events
    evts = events.get("events", [])
    # Find free blocks
    busy_times = []
    for e in evts:
        try:
            start = datetime.fromisoformat(e["start"].replace("Z",""))
            end = datetime.fromisoformat(e["end"].replace("Z",""))
            busy_times.append((start, end))
        except: pass
    # Suggest 2-hour deep work blocks
    suggestions = []
    now = datetime.utcnow()
    for day_offset in range(7):
        day = now + timedelta(days=day_offset)
        # Check 9-11am and 2-4pm slots
        for hour in [9, 14]:
            slot_start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            slot_end = slot_start + timedelta(hours=2)
            conflict = any(not (slot_end <= b[0] or slot_start >= b[1]) for b in busy_times)
            if not conflict:
                suggestions.append({"date": slot_start.strftime("%Y-%m-%d"), "time": f"{hour}:00-{hour+2}:00", "type": "deep_work_block"})
    return {"ok": True, "upcoming_events": len(evts), "suggested_focus_blocks": suggestions[:5]}
