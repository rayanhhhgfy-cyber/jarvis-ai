# ====================================================================
# JARVIS OMEGA — Android Agent (Master Control)
# ====================================================================
"""
Full-blown Android Control Agent using ADB.
Capable of deep device interaction, app automation, and system configuration.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from local_client.process_manager import local_process_manager
from shared.logger import get_logger

log = get_logger("agent_android")

class AgentAndroid:
    """
    Android Master Control. Controls phones via ADB with granular precision.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_android"
        self.agent_type = AgentType.ANDROID

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("android_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "status")

            if action == "click":
                result_data = await self._adb_click(task)
            elif action == "type":
                result_data = await self._adb_type(task)
            elif action == "swipe":
                result_data = await self._adb_swipe(task)
            elif action == "key":
                result_data = await self._adb_keyevent(task)
            elif action == "app":
                result_data = await self._adb_manage_app(task)
            elif action == "intent":
                result_data = await self._adb_send_intent(task)
            elif action == "screenshot":
                result_data = await self._adb_screenshot(task)
            elif action == "status":
                result_data = await self._adb_status(task)
            else:
                raise ValueError(f"Unknown Android action: {action}")

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
            log.error("android_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _run_adb(self, command: str) -> str:
        proc_id = f"adb_{int(time.time()*1000)}"
        success, msg = await local_process_manager.spawn_process(proc_id, f"adb {command}")
        if not success:
            return f"Error: {msg}"
        code, stdout, stderr = await local_process_manager.wait_process(proc_id)
        return stdout if code == 0 else stderr

    async def _adb_click(self, task: TaskDefinition) -> Dict[str, Any]:
        x, y = task.payload.get("coords", [500, 500])
        output = await self._run_adb(f"shell input tap {x} {y}")
        return {"status": "clicked", "coords": [x, y], "output": output}

    async def _adb_type(self, task: TaskDefinition) -> Dict[str, Any]:
        text = task.payload.get("text", "")
        # Escape spaces for ADB
        text_escaped = text.replace(" ", "%s")
        output = await self._run_adb(f"shell input text {text_escaped}")
        return {"status": "typed", "text": text}

    async def _adb_keyevent(self, task: TaskDefinition) -> Dict[str, Any]:
        keycode = task.payload.get("keycode", "KEYCODE_HOME")
        output = await self._run_adb(f"shell input keyevent {keycode}")
        return {"status": "key_sent", "keycode": keycode}

    async def _adb_swipe(self, task: TaskDefinition) -> Dict[str, Any]:
        start = task.payload.get("start", [100, 100])
        end = task.payload.get("end", [500, 500])
        duration = task.payload.get("duration", 300)
        output = await self._run_adb(f"shell input swipe {start[0]} {start[1]} {end[0]} {end[1]} {duration}")
        return {"status": "swiped", "from": start, "to": end}

    async def _adb_manage_app(self, task: TaskDefinition) -> Dict[str, Any]:
        pkg = task.payload.get("package")
        op = task.payload.get("op", "start")
        if op == "start":
            await self._run_adb(f"shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        elif op == "stop":
            await self._run_adb(f"shell am force-stop {pkg}")
        elif op == "clear":
            await self._run_adb(f"shell pm clear {pkg}")
        return {"status": f"app_{op}", "package": pkg}

    async def _adb_send_intent(self, task: TaskDefinition) -> Dict[str, Any]:
        uri = task.payload.get("uri")
        output = await self._run_adb(f"shell am start -a android.intent.action.VIEW -d {uri}")
        return {"status": "intent_sent", "uri": uri}

    async def _adb_screenshot(self, task: TaskDefinition) -> Dict[str, Any]:
        filename = f"android_shot_{int(time.time())}.png"
        path = f"shared/screenshots/{filename}"
        os.makedirs("shared/screenshots", exist_ok=True)
        await self._run_adb(f"shell screencap -p /sdcard/screen.png")
        await self._run_adb(f"pull /sdcard/screen.png {path}")
        return {"status": "success", "file_path": path}

    async def _adb_status(self, task: TaskDefinition) -> Dict[str, Any]:
        devices = await self._run_adb("devices")
        battery = await self._run_adb("shell dumpsys battery")
        return {"devices": devices, "battery_info": battery}
