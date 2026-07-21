# ====================================================================
# JARVIS OMEGA — Vision Agent
# ====================================================================
"""
Specialized Vision Agent for screenshot analysis, OCR, visual debugging,
and UI structural inspection using Qwen 2.5 VL via OpenRouter.

Phase 4: real OpenRouter chat-completion call with a base64-encoded image
payload against ``settings.qwen_vision_model``. Falls back to a stub only if
the OPENROUTER_API_KEY is missing or the network call fails.
"""

from __future__ import annotations

import os
import time
import base64
import json
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

import httpx

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.screenshot_manager import screenshot_manager
from shared.logger import get_logger
from backend.config import settings

log = get_logger("agent_vision")


_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_VISION_USER_AGENT = "JARVIS-OMEGA-Vision/1.0 (+https://github.com/google-deepmind/jarvis-omega)"

# The OCR instruction sent to Qwen 2.5 VL. Tuned to return STRICT JSON.
_DEFAULT_OCR_INSTRUCTION = (
    "You are an OCR engine. Read all visible text in the supplied image and "
    "return STRICT JSON of the form:\n"
    '  {"text": string, "regions": [{"text": string, "x": number, "y": number}, ...]}\n'
    "where ``text`` is the full plain-text transcript of the image and "
    "``regions`` lists individual text fragments with rough pixel coordinates "
    "(origin top-left). If no text is present, return "
    '{\"text\":\"\",\"regions\":[]}. Do NOT wrap the JSON in markdown fences.'
)


class AgentVision:
    """
    Computer Vision agent. Captures screen data, parses desktop components,
    and runs visual OCR processing via Qwen 2.5 VL on OpenRouter.
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

            if action in ("capture", "screenshot"):
                result_data = await self._capture_and_analyze(task)
            elif action == "ocr":
                result_data = await self._perform_ocr(task)
            elif action == "describe":
                result_data = await self._describe_image(task)
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

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    async def _capture_and_analyze(self, task: TaskDefinition) -> Dict[str, Any]:
        """Captures a screenshot of all displays and converts it to a base64 payload."""
        log.info("capturing_screen_for_agent_vision")

        filepath = task.payload.get("file_path") or f"temp_screenshot_{task.task_id}.png"
        success = await screenshot_manager.capture_screenshot(filepath)

        if not success or not os.path.exists(filepath):
            raise RuntimeError("Failed to capture active monitor display")

        with open(filepath, "rb") as image_file:
            b64_data = base64.b64encode(image_file.read()).decode("utf-8")

        try:
            size_bytes = os.path.getsize(filepath)
        except OSError:
            size_bytes = 0

        return {
            "screenshot_captured": True,
            "file_path": os.path.abspath(filepath),
            "image_format": "png",
            "base64_length": len(b64_data),
            "size_bytes": size_bytes,
            "timestamp": datetime.utcnow().isoformat(),
            "dimensions": "Multi-monitor detection active",
        }

    # ------------------------------------------------------------------
    # OCR via Qwen 2.5 VL
    # ------------------------------------------------------------------

    async def _perform_ocr(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Performs OCR on a captured screenshot or an explicit image path.
        Calls Qwen 2.5 VL via OpenRouter chat-completions with a base64 image
        payload. Falls back to an explicit empty result if the API call fails.
        """
        image_path = task.payload.get("image_path")
        capture_first = False

        if not image_path:
            # Capture current screen as the source.
            capture_first = True
        else:
            # Caller-supplied path — verify it exists before going to the network.
            if not Path(image_path).is_file():
                raise FileNotFoundError(f"image_path does not exist: {image_path}")

        if capture_first:
            captured = await self._capture_and_analyze(task)
            image_path = captured["file_path"]

        instruction = task.payload.get("instruction") or _DEFAULT_OCR_INSTRUCTION

        try:
            b64 = self._encode_image(image_path)
        except Exception as enc_err:
            raise RuntimeError(f"failed to encode image for OCR: {enc_err}") from enc_err

        # Try the real OpenRouter call.
        try:
            parsed = await self._call_qwen_vl(
                b64_image=b64,
                mime_type="image/png",
                instruction=instruction,
            )
            parsed["ocr_status"] = "completed"
            parsed["ocr_backend"] = "qwen2.5-vl"
            parsed["image_path"] = image_path
            return parsed
        except Exception as ocr_err:
            log.warning("qwen_ocr_failed_using_empty_fallback", error=str(ocr_err))
            return {
                "ocr_status": "failed",
                "ocr_backend": "none",
                "image_path": image_path,
                "text": "",
                "regions": [],
                "error": str(ocr_err),
            }

    # ------------------------------------------------------------------
    # Image description (less strict OCR — natural language)
    # ------------------------------------------------------------------

    async def _describe_image(self, task: TaskDefinition) -> Dict[str, Any]:
        """Natural-language description of an image via Qwen 2.5 VL."""
        image_path = task.payload.get("image_path")
        if not image_path or not Path(image_path).is_file():
            raise FileNotFoundError(f"image_path required and must exist: {image_path}")

        question = task.payload.get("question") or "Describe this image concisely."
        b64 = self._encode_image(image_path)
        try:
            description = await self._call_qwen_vl(
                b64_image=b64,
                mime_type="image/png",
                instruction=question,
                raw_text=True,
            )
            return {
                "describe_status": "completed",
                "image_path": image_path,
                "description": description,
                "backend": "qwen2.5-vl",
            }
        except Exception as desc_err:
            return {
                "describe_status": "failed",
                "image_path": image_path,
                "description": "",
                "error": str(desc_err),
            }

    # ------------------------------------------------------------------
    # Qwen 2.5 VL call helper
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("utf-8")

    async def _call_qwen_vl(
        self,
        b64_image: str,
        mime_type: str,
        instruction: str,
        raw_text: bool = False,
    ) -> Dict[str, Any] | str:
        """
        POST a chat-completion to OpenRouter with a Qwen 2.5 VL vision payload.

        Args:
            b64_image: base64-encoded image bytes (no data: prefix).
            mime_type: image MIME type, e.g. ``image/png``.
            instruction: text instruction / question for the vision model.
            raw_text: when True, return the raw model text instead of parsed JSON.

        Raises on any failure (network, auth, non-2xx, empty body). Caller
        handles fallback.
        """
        api_key = settings.openrouter_api_key
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured — cannot call Qwen VL")

        data_url = f"data:{mime_type};base64,{b64_image}"

        payload = {
            "model": settings.qwen_vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            "temperature": 0.1,  # OCR is deterministic-ish
            "max_tokens": 1500,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/google-deepmind/jarvis-omega",
            "X-Title": "JARVIS OMEGA Vision",
            "User-Agent": _VISION_USER_AGENT,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(_OPENROUTER_CHAT_URL, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"OpenRouter HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as parse_err:
            raise RuntimeError(f"OpenRouter response missing content: {parse_err}") from parse_err

        if raw_text:
            return text or ""

        # Parse STRICT JSON. Tolerate accidental ```json fences or trailing prose.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fall back: treat whole response as ``text``.
            parsed = {"text": text, "regions": []}

        if not isinstance(parsed, dict):
            parsed = {"text": str(text), "regions": []}
        parsed.setdefault("text", "")
        parsed.setdefault("regions", [])
        return parsed
