"""
Pattern detection and workflow automation service.
Tracks command execution history and detects repeated sequences
that can be turned into reusable workflows.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.logger import get_logger

log = get_logger("pattern_detector")


class PatternDetector:
    """
    Detects repeated command patterns in execution history and
    suggests/creates automated workflows.
    """

    def __init__(self):
        self._history: List[Dict[str, Any]] = []
        self._workflows: Dict[str, Dict[str, Any]] = {}
        self._patterns_file = Path("./storage/command_patterns.json")
        self._workflows_file = Path("./storage/workflows.json")
        self._load()

    def record_execution(self, command: str, success: bool, output: str = "", user_intent: str = "") -> None:
        """Record a command execution for pattern analysis."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "command": command,
            "success": success,
            "output_preview": output[:200],
            "user_intent": user_intent,
            "command_type": self._classify_command(command),
        }
        self._history.append(entry)
        # Keep last 200 entries
        if len(self._history) > 200:
            self._history = self._history[-200:]
        self._save()

    def detect_patterns(self) -> List[Dict[str, Any]]:
        """
        Scan execution history for repeated command sequences.
        Returns detected patterns with frequency scores.
        """
        if len(self._history) < 4:
            return []

        patterns = []
        sequence_lengths = [2, 3]  # Look for 2-step and 3-step patterns

        for seq_len in sequence_lengths:
            sequences: Dict[str, List[int]] = {}
            for i in range(len(self._history) - seq_len + 1):
                seq = self._history[i:i + seq_len]
                key = self._sequence_key(seq)
                if key not in sequences:
                    sequences[key] = []
                sequences[key].append(i)

            for key, indices in sequences.items():
                if len(indices) >= 2:  # Repeated at least twice
                    seq_entries = [self._history[i] for i in indices[:seq_len]]
                    patterns.append({
                        "pattern_key": key,
                        "frequency": len(indices),
                        "sequence_length": seq_len,
                        "last_detected": seq_entries[-1]["timestamp"],
                        "commands": [e["command"] for e in seq_entries],
                        "command_types": [e["command_type"] for e in seq_entries],
                        "suggest_workflow": len(indices) >= 3,  # Suggest if 3+ repetitions
                    })

        patterns.sort(key=lambda p: p["frequency"], reverse=True)
        return patterns

    def suggest_workflow_name(self, pattern: Dict[str, Any]) -> str:
        """Generate a human-readable workflow name from a pattern."""
        types = pattern.get("command_types", [])
        type_names = {
            "browser": "Browser",
            "desktop": "Desktop",
            "file": "File",
            "search": "Search",
            "powershell": "PowerShell",
            "media": "Media",
            "other": "Command",
        }
        labels = [type_names.get(t, t) for t in types if t]
        return " → ".join(labels) if labels else "Workflow"

    def create_workflow(self, name: str, commands: List[str], description: str = "") -> Dict[str, Any]:
        """Create a reusable workflow from a list of commands."""
        workflow_id = f"wf_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        workflow = {
            "workflow_id": workflow_id,
            "name": name,
            "description": description or f"Automated workflow with {len(commands)} steps",
            "commands": commands,
            "step_count": len(commands),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "run_count": 0,
        }
        self._workflows[workflow_id] = workflow
        self._save()
        log.info("workflow_created", workflow_id=workflow_id, name=name, steps=len(commands))
        return workflow

    def get_workflows(self) -> List[Dict[str, Any]]:
        """Return all saved workflows."""
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            self._save()
            return True
        return False

    def run_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Execute a workflow's commands sequentially.
        Returns execution results.
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return {"success": False, "error": f"Workflow {workflow_id} not found"}

        import asyncio
        from backend.routers.router_chat import _dispatch_and_wait

        results = []
        all_success = True

        for i, cmd in enumerate(workflow["commands"]):
            try:
                result = asyncio.run(_dispatch_and_wait(cmd, f"Workflow step {i + 1}: {cmd[:60]}", timeout=30.0))
                step_result = {
                    "step": i + 1,
                    "command": cmd,
                    "success": result.get("completed", False),
                    "output": result.get("stdout", ""),
                    "error": result.get("stderr", ""),
                }
                if not step_result["success"]:
                    all_success = False
            except Exception as e:
                step_result = {"step": i + 1, "command": cmd, "success": False, "error": str(e)}
                all_success = False

            results.append(step_result)

        workflow["run_count"] = workflow.get("run_count", 0) + 1
        self._save()

        return {
            "success": all_success,
            "workflow_id": workflow_id,
            "name": workflow["name"],
            "steps": results,
            "all_success": all_success,
        }

    def _classify_command(self, command: str) -> str:
        """Classify a command into a type category."""
        cmd_lower = command.lower()
        if "browser_" in cmd_lower:
            return "browser"
        if "desktop_" in cmd_lower:
            return "desktop"
        if any(kw in cmd_lower for kw in ["set-content", "out-file", "new-item", "copy-item", "remove-item"]):
            return "file"
        if any(kw in cmd_lower for kw in ["search_web", "fetch_url", "search_maps"]):
            return "search"
        if any(kw in cmd_lower for kw in ["generate_image", "generate_video"]):
            return "media"
        if "powershell" in cmd_lower:
            return "powershell"
        return "other"

    def _sequence_key(self, sequence: List[Dict[str, Any]]) -> str:
        """Create a hashable key for a command sequence."""
        types = [e["command_type"] for e in sequence]
        return "|".join(types)

    def _save(self) -> None:
        """Persist patterns and workflows to disk."""
        try:
            data = {
                "history": self._history,
                "workflows": self._workflows,
            }
            self._patterns_file.parent.mkdir(parents=True, exist_ok=True)
            self._patterns_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error("pattern_save_failed", error=str(e))

    def _load(self) -> None:
        """Load persisted data from disk."""
        try:
            if self._workflows_file.exists():
                wf_data = json.loads(self._workflows_file.read_text())
                self._workflows = wf_data if isinstance(wf_data, dict) else {}

            if self._patterns_file.exists():
                data = json.loads(self._patterns_file.read_text())
                self._history = data.get("history", [])
                self._workflows = data.get("workflows", self._workflows)
        except Exception as e:
            log.error("pattern_load_failed", error=str(e))

    def get_stats(self) -> Dict[str, Any]:
        """Return pattern detection statistics."""
        patterns = self.detect_patterns()
        return {
            "total_commands_recorded": len(self._history),
            "patterns_detected": len(patterns),
            "workflows_created": len(self._workflows),
            "high_frequency_patterns": [p for p in patterns if p["frequency"] >= 3],
            "recent_commands": self._history[-10:] if self._history else [],
        }


pattern_detector = PatternDetector()
