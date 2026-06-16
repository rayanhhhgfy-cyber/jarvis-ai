"""
JARVIS OMEGA — Continuous Learning Loop
Stores and retrieves lessons learned from every task, failure, and success.
All agents consult this before acting and write to it after acting.
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from shared.logger import get_logger

log = get_logger("learning_loop")

LESSONS_FILE = os.path.join(os.path.dirname(__file__), "lessons_learned.json")
CAPABILITIES_FILE = os.path.join(os.path.dirname(__file__), "capabilities_cache.json")

class LearningLoop:
    """
    Persistent learning system. Stores every lesson, success pattern,
    and error analysis. Agents query this before tasks and write to it after.
    This is how JARVIS gets smarter over time without retraining.
    """

    def __init__(self):
        self.lessons = self._load_lessons()
        self.capabilities = self._load_capabilities()

    def _load_lessons(self) -> List[Dict[str, Any]]:
        if os.path.exists(LESSONS_FILE):
            with open(LESSONS_FILE, "r") as f:
                return json.load(f)
        return []

    def _load_capabilities(self) -> Dict[str, Any]:
        if os.path.exists(CAPABILITIES_FILE):
            with open(CAPABILITIES_FILE, "r") as f:
                return json.load(f)
        return {"self_added_tools": [], "self_added_actions": [], "modified_files": []}

    def _save_lessons(self):
        os.makedirs(os.path.dirname(LESSONS_FILE), exist_ok=True)
        with open(LESSONS_FILE, "w") as f:
            json.dump(self.lessons, f, indent=2)

    def _save_capabilities(self):
        os.makedirs(os.path.dirname(CAPABILITIES_FILE), exist_ok=True)
        with open(CAPABILITIES_FILE, "w") as f:
            json.dump(self.capabilities, f, indent=2)

    def remember_lesson(self, task_description: str, error_pattern: str,
                        root_cause: str, solution: str, file_path: Optional[str] = None,
                        success: bool = False):
        """Store a lesson learned from success or failure."""
        lesson = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_description": task_description,
            "error_pattern": error_pattern,
            "root_cause": root_cause,
            "solution": solution,
            "file_path": file_path,
            "success": success,
            "applied_count": 0
        }
        self.lessons.append(lesson)
        self._save_lessons()
        log.info("lesson_recorded", error_pattern=error_pattern, solution_length=len(solution))

    def query_lessons(self, task_description: str) -> List[Dict[str, Any]]:
        """Find relevant past lessons for a given task description.
        Matches by keyword overlap between task description and stored patterns."""
        keywords = set(task_description.lower().split())
        scored = []
        for lesson in self.lessons:
            lesson_text = f"{lesson['task_description']} {lesson['error_pattern']} {lesson['root_cause']} {lesson['solution']}"
            lesson_keywords = set(lesson_text.lower().split())
            overlap = len(keywords & lesson_keywords)
            if overlap > 0:
                scored.append((overlap, lesson))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:5]]

    def record_self_modification(self, file_path: str, description: str, tool_name: Optional[str] = None, action_name: Optional[str] = None):
        """Record that the agent modified its own code to add a capability."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file_path": file_path,
            "description": description,
            "tool_name": tool_name,
            "action_name": action_name
        }
        self.capabilities["modified_files"].append(entry)
        if tool_name:
            self.capabilities["self_added_tools"].append(entry)
        if action_name:
            self.capabilities["self_added_actions"].append(entry)
        self._save_capabilities()
        log.info("self_modification_recorded", file=file_path, desc=description)

    def get_stats(self) -> Dict[str, Any]:
        """Return learning statistics."""
        return {
            "total_lessons": len(self.lessons),
            "total_self_modifications": len(self.capabilities["modified_files"]),
            "self_added_tools": self.capabilities["self_added_tools"],
            "self_added_actions": self.capabilities["self_added_actions"],
            "lessons_by_type": {
                "successes": sum(1 for l in self.lessons if l["success"]),
                "failures": sum(1 for l in self.lessons if not l["success"])
            }
        }

# Global singleton
learning_loop = LearningLoop()
