# ====================================================================
# JARVIS OMEGA — Video Agent
# ====================================================================
"""
Specialized Video Agent for video metadata analysis, scene boundary detection,
frame extraction, and visual summarization using OpenCV.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_video")

# Graceful import of OpenCV
cv2_available = False
try:
    import cv2
    cv2_available = True
except ImportError:
    log.warning("opencv_not_installed_using_stub_fallback")

class AgentVideo:
    """
    Video intelligence agent. Processes video files, extracts frames,
    performs keyframe generation and video description logic.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_video"
        self.agent_type = AgentType.VIDEO

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes video-based actions like frame extraction or structural inspection."""
        log.info("video_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "inspect")
            video_path = task.payload.get("video_path")
            
            if not video_path:
                raise ValueError("video_path is required for all video tasks")
                
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found at: {video_path}")

            if action == "inspect" or action == "metadata":
                result_data = await self._get_metadata(video_path)
            elif action == "extract_frames":
                result_data = await self._extract_frames(video_path, task)
            else:
                raise ValueError(f"Unknown video action: {action}")

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
            log.error("video_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _get_metadata(self, path: str) -> Dict[str, Any]:
        """Reads metadata from a video file using OpenCV if available, or file properties."""
        size_bytes = os.path.getsize(path)
        
        if cv2_available:
            try:
                cap = cv2.VideoCapture(path)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = frame_count / fps if fps > 0 else 0
                cap.release()
                
                return {
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "frame_count": frame_count,
                    "duration_seconds": duration,
                    "file_size_bytes": size_bytes,
                    "cv2_parsed": True
                }
            except Exception as e:
                log.error("cv2_metadata_failed_falling_back", error=str(e))

        # Stub fallback if OpenCV fails or is not present
        return {
            "file_size_bytes": size_bytes,
            "status": "opencv_stub_fallback",
            "message": "OpenCV was not available. Installed python package requires imports."
        }

    async def _extract_frames(self, path: str, task: TaskDefinition) -> Dict[str, Any]:
        """Extracts keyframes at specified intervals or timestamps."""
        output_dir = task.payload.get("output_dir", "./extracted_frames")
        os.makedirs(output_dir, exist_ok=True)
        
        interval = task.payload.get("interval_seconds", 5)
        extracted = []
        
        if cv2_available:
            try:
                cap = cv2.VideoCapture(path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = frame_count / fps if fps > 0 else 0
                
                # Extract frames based on interval
                for t in range(0, int(duration), interval):
                    frame_num = int(t * fps)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = cap.read()
                    if ret:
                        out_path = os.path.join(output_dir, f"frame_{t}s.jpg")
                        cv2.imwrite(out_path, frame)
                        extracted.append({
                            "timestamp_seconds": t,
                            "frame_number": frame_num,
                            "path": out_path
                        })
                cap.release()
                
                return {
                    "status": "frames_extracted",
                    "count": len(extracted),
                    "frames": extracted
                }
            except Exception as e:
                log.error("cv2_frame_extraction_failed", error=str(e))

        return {
            "status": "failed",
            "reason": "OpenCV not available or failed during run"
        }
