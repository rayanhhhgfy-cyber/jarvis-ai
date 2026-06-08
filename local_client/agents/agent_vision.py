from __future__ import annotations

import os
import time
import base64
import traceback
from typing import Dict, Any, Optional
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.screenshot_manager import screenshot_manager
from backend.services.vision_service import vision_service
from backend.vision.dynamic_sampler import dynamic_sampler
from backend.vision.captcha_solver import captcha_solver
from shared.logger import get_logger

log = get_logger("agent_vision")


class AgentVision:

    def __init__(self) -> None:
        self.agent_id = "agent_vision"
        self.agent_type = AgentType.VISION

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("vision_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "capture")
            if action in ("capture", "screenshot"):
                result_data = await self._capture_and_analyze(task)
            elif action == "ocr":
                result_data = await self._perform_ocr(task)
            elif action == "captcha":
                result_data = await self._solve_captcha(task)
            elif action == "detect_ui":
                result_data = await self._detect_ui(task)
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
        filepath = f"temp_screenshot_{task.task_id}.png"
        success = await screenshot_manager.capture_screenshot(filepath)
        if not success or not os.path.exists(filepath):
            raise RuntimeError("Failed to capture screen")

        with open(filepath, "rb") as f:
            image_bytes = f.read()

        if not dynamic_sampler.should_analyze(image_bytes):
            return {"screenshot_captured": True, "dynamic_skip": True, "file_path": os.path.abspath(filepath)}

        prompt = task.payload.get("prompt", "Analyze this screenshot and describe what you see.")
        analysis = await vision_service.analyze_image_bytes(image_bytes, prompt)

        return {
            "screenshot_captured": True,
            "file_path": os.path.abspath(filepath),
            "image_format": "png",
            "base64_length": len(base64.b64encode(image_bytes).decode()),
            "analysis": analysis,
            "timestamp": datetime.utcnow().isoformat(),
            "sampler_stats": dynamic_sampler.stats,
        }

    async def _perform_ocr(self, task: TaskDefinition) -> Dict[str, Any]:
        image_path = task.payload.get("image_path")
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        else:
            filepath = f"temp_ocr_{task.task_id}.png"
            await screenshot_manager.capture_screenshot(filepath)
            with open(filepath, "rb") as f:
                image_bytes = f.read()

        ocr_prompt = "Extract and return ALL visible text in this image. Output only the extracted text."
        detected_text = await vision_service.analyze_image_bytes(image_bytes, ocr_prompt)

        return {
            "ocr_status": "completed",
            "image_path": image_path or filepath,
            "detected_text": detected_text,
            "char_count": len(detected_text),
        }

    async def _solve_captcha(self, task: TaskDefinition) -> Dict[str, Any]:
        image_path = task.payload.get("image_path")
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        else:
            filepath = f"temp_captcha_{task.task_id}.png"
            await screenshot_manager.capture_screenshot(filepath)
            with open(filepath, "rb") as f:
                image_bytes = f.read()

        solution = await captcha_solver.solve(image_bytes)
        return {
            "captcha_analysis": solution,
            "image_path": image_path or filepath,
        }

    async def _detect_ui(self, task: TaskDefinition) -> Dict[str, Any]:
        filepath = f"temp_ui_{task.task_id}.png"
        await screenshot_manager.capture_screenshot(filepath)
        with open(filepath, "rb") as f:
            image_bytes = f.read()

        ui_prompt = (
            "Analyze this UI screenshot and identify all interactive elements. "
            "For each element, provide: type (button/input/link/text), "
            "approximate position (x,y), dimensions (w,h), and any visible text. "
            "Output as structured JSON."
        )
        analysis = await vision_service.analyze_image_bytes(image_bytes, ui_prompt)

        return {
            "ui_elements": analysis,
            "file_path": os.path.abspath(filepath),
        }
