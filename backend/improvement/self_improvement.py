from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from shared.logger import get_logger
from shared.constants import TaskStatus
from shared.models import TaskDefinition, MemoryEntry, MemoryQuery
from shared.constants import MemoryCategory
from backend.services.llm_service import llm_service
from backend.memory_engine import memory_engine
from backend.scheduler import scheduler

log = get_logger("self_improvement")

LESSONS_FILE = Path("./storage/lessons.json")


class SelfImprovementLoop:
    """
    Pillar X: Analyzes failed tasks, user corrections, and performance data
    to dynamically update JARVIS's internal instructions and become smarter.
    """

    def __init__(self) -> None:
        self._lessons: List[Dict[str, Any]] = self._load_lessons()

    def _load_lessons(self) -> List[Dict[str, Any]]:
        if LESSONS_FILE.exists():
            try:
                return json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_lessons(self) -> None:
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LESSONS_FILE.write_text(json.dumps(self._lessons, indent=2, default=str), encoding="utf-8")

    async def register_schedules(self) -> None:
        scheduler.schedule_cron(
            "self_improvement_weekly",
            self._weekly_analysis,
            "0 3 * * 0",
            description="Weekly self-improvement analysis",
        )
        log.info("self_improvement_schedules_registered")

    async def record_failure(self, task: TaskDefinition, error: str) -> None:
        lesson = {
            "type": "failure",
            "task_id": task.task_id,
            "title": task.title,
            "agent_type": task.agent_type.value,
            "error": error[:500],
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._lessons.append(lesson)
        self._save_lessons()
        log.info("failure_recorded", task_id=task.task_id)

    async def record_correction(self, user_message: str, correction: str) -> None:
        lesson = {
            "type": "correction",
            "user_said": user_message,
            "correction": correction,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._lessons.append(lesson)
        self._save_lessons()
        log.info("correction_recorded", user_message=user_message[:100])

    async def generate_insights(self) -> str:
        if not self._lessons:
            return "No lessons recorded yet."

        recent = self._lessons[-20:]
        lessons_text = "\n".join(
            f"- [{l['type']}] {l.get('title', l.get('user_said', 'N/A'))}: {l.get('error', l.get('correction', ''))[:200]}"
            for l in recent
        )

        insight = await llm_service.get_response(
            user_message=(
                "Analyze these recent failures and corrections from my operation log. "
                "Identify patterns, root causes, and suggest specific improvements "
                "to my system instructions or behavior.\n\n"
                f"Lessons:\n{lessons_text}"
            ),
            inject_memory=False,
            system_instructions="You are JARVIS's self-improvement subsystem. Be analytical and specific.",
        )
        return insight

    async def _weekly_analysis(self) -> None:
        log.info("self_improvement_weekly_analysis")
        insights = await self.generate_insights()

        entry = MemoryEntry(
            category=MemoryCategory.DEBUGGING,
            content=f"Weekly self-improvement insights:\n{insights}",
            source="self_improvement",
            tags=["self_improvement", "weekly", "analysis"],
            metadata={"lesson_count": len(self._lessons)},
        )
        await memory_engine.store(entry)
        log.info("weekly_analysis_stored", insights_len=len(insights))

    def get_lessons(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._lessons[-limit:]

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_lessons": len(self._lessons),
            "failures": sum(1 for l in self._lessons if l["type"] == "failure"),
            "corrections": sum(1 for l in self._lessons if l["type"] == "correction"),
        }


self_improvement = SelfImprovementLoop()
