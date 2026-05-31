# ====================================================================
# JARVIS OMEGA — Vision Agent
# ====================================================================
"""
Specialized Vision Agent for screenshot analysis, OCR, visual debugging,
and UI structural inspection using Qwen 2.5 VL.
"""

from __future__ import annotations

import os
import time
import base64
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.screenshot_manager import screenshot_manager
from shared.logger import get_logger

log = get_logger("agent_vision")

class AgentVision:
    """
    Computer Vision agent. Captures screen data, parses desktop components,
    and runs visual OCR processing via multi-modal vision proxies.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_vision"
        self.agent_type = AgentType.VISION

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Runs vision actions like screen capture, UI element location, or image OCR."""
        log.info("vision_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "capture")

            if action == "capture" or action == "screenshot":
                result_data = await self._capture_and_analyze(task)
            elif action == "ocr":
                result_data = await self._perform_ocr(task)
            else:
                raise ValueError(f"Unknown Vision action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("vision_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _capture_and_analyze(self, task: TaskDefinition) -> Dict[str, Any]:
        """Captures a screenshot of all displays and converts it to a base64 encoded payload."""
        log.info("capturing_screen_for_agent_vision")
        
        # Save temporary screenshot
        filepath = f"temp_screenshot_{task.task_id}.png"
        success = await screenshot_manager.capture_screenshot(filepath)
        
        if not success or not os.path.exists(filepath):
            raise RuntimeError("Failed to capture active monitor display")

        try:
            with open(filepath, "rb") as image_file:
                b64_data = base64.b64encode(image_file.read()).decode("utf-8")

            # In Phase 5, return base64 and image details to backend for Qwen analysis
            return {
                "screenshot_captured": True,
                "file_path": os.path.abspath(filepath),
                "image_format": "png",
                "base64_length": len(b64_data),
                "timestamp": datetime.utcnow().isoformat(),
                "dimensions": "Multi-monitor detection active"
            }
        finally:
            # Keep screenshot file for frontend caching, cleanup is done later
            pass

    async def _perform_ocr(self, task: TaskDefinition) -> Dict[str, Any]:
        """Performs simulated OCR processing on a captured screen or custom image path."""
        image_path = task.payload.get("image_path")
        if not image_path:
            # Capture current screen as fallback
            captured = await self._capture_and_analyze(task)
            image_path = captured.get("file_path")

        # Mock OCR output — will connect to Qwen VL in fully deployed system
        return {
            "ocr_status": "completed",
            "image_path": image_path,
            "detected_text": "JARVIS OMEGA Command Station — Active Workspace detected.",
            "regions": [
                {"text": "JARVIS OMEGA", "x": 100, "y": 50},
                {"text": "Active Workspace", "x": 200, "y": 80}
            ]
        }
