# Phase 18: Habit Tracker (REAL)
from __future__ import annotations
import json
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

_HABITS_PATH = Path("./storage/habits.json")

def _load():
    return json.loads(_HABITS_PATH.read_text()) if _HABITS_PATH.exists() else {}

def _save(data):
    _HABITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HABITS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

@tool(name="habit.add", description="Add a daily habit to track.", parameters={"type":"object","properties":{"name":{"type":"string"},"target_per_week":{"type":"integer","default":7}},"required":["name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="habit_tracker")
async def add(name: str, target_per_week: int = 7) -> Dict[str, Any]:
    data = _load()
    data[name] = {"target": target_per_week, "completions": [], "created_at": datetime.utcnow().isoformat()}
    _save(data)
    return {"ok": True, "habit": name, "target": target_per_week}

@tool(name="habit.check", description="Mark a habit as done for today.", parameters={"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="habit_tracker")
async def check(name: str) -> Dict[str, Any]:
    data = _load()
    if name not in data: return {"ok": False, "error": "habit not found"}
    today = date.today().isoformat()
    if today not in data[name]["completions"]:
        data[name]["completions"].append(today)
        _save(data)
    streak = _calculate_streak(data[name]["completions"])
    return {"ok": True, "habit": name, "streak_days": streak, "total_completions": len(data[name]["completions"])}

@tool(name="habit.stats", description="Show all habits + streaks.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="habit_tracker")
async def stats() -> Dict[str, Any]:
    data = _load()
    result = []
    for name, info in data.items():
        streak = _calculate_streak(info["completions"])
        result.append({"habit": name, "streak": streak, "total": len(info["completions"]), "target": info["target"]})
    return {"ok": True, "habits": result}

def _calculate_streak(completions):
    if not completions: return 0
    streak = 0
    d = date.today()
    while d.isoformat() in completions:
        streak += 1
        from datetime import timedelta
        d -= timedelta(days=1)
    return streak
