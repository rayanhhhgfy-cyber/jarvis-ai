# ====================================================================
# JARVIS OMEGA — Local Process Manager
# ====================================================================
"""
Spawns and monitors local child subprocesses. Tracks CPU, memory, PIDs,
and enforces execution limits, termination, and process cleanup.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from typing import Dict, Optional, Tuple, Any

import psutil

from shared.logger import get_logger

log = get_logger("process_manager")


class LocalProcessManager:
    """
    Manages process lifecycles for local commands and spawned agent operations.
    """

    def __init__(self) -> None:
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._stats: Dict[str, Dict[str, Any]] = {}

    async def spawn_process(
        self,
        process_id: str,
        command: str | list[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, str]:
        """Spawns a background process asynchronously."""
        if process_id in self._processes:
            return False, "Process ID already active"

        cmd_str = " ".join(command) if isinstance(command, list) else command
        log.info("spawning_process", process_id=process_id, command=cmd_str)

        try:
            # Prepare execution environment
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=run_env,
            )

            self._processes[process_id] = proc
            self._stats[process_id] = {
                "pid": proc.pid,
                "command": cmd_str,
                "spawn_time": asyncio.get_event_loop().time(),
            }
            return True, f"Spawned successfully (PID: {proc.pid})"

        except Exception as e:
            log.error("process_spawn_failed", process_id=process_id, error=str(e))
            return False, f"Failed to spawn process: {str(e)}"

    async def wait_process(self, process_id: str) -> Tuple[int, str, str]:
        """Waits for process completion, returning exit code, stdout, and stderr."""
        proc = self._processes.get(process_id)
        if not proc:
            return -1, "", "Process not found"

        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        # Cleanup
        self._processes.pop(process_id, None)
        self._stats.pop(process_id, None)

        log.info("process_completed", process_id=process_id, exit_code=proc.returncode)
        return proc.returncode, stdout, stderr

    async def terminate_process(self, process_id: str) -> bool:
        """Gracefully terminates a process by ID."""
        proc = self._processes.get(process_id)
        if not proc:
            return False

        log.info("terminating_process", process_id=process_id, pid=proc.pid)
        try:
            # Terminate parent and all sub-children
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            
            await proc.wait()
            self._processes.pop(process_id, None)
            self._stats.pop(process_id, None)
            return True
        except Exception as e:
            log.error("process_termination_failed", process_id=process_id, error=str(e))
            return False

    def get_process_vitals(self, process_id: str) -> Dict[str, float]:
        """Retrieves CPU and RAM utilization for a running process."""
        stats = self._stats.get(process_id)
        if not stats:
            return {"cpu_percent": 0.0, "memory_mb": 0.0}

        pid = stats["pid"]
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                cpu = p.cpu_percent(interval=None)
                mem = p.memory_info().rss / (1024 * 1024)
            return {"cpu_percent": cpu, "memory_mb": mem}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"cpu_percent": 0.0, "memory_mb": 0.0}

    def list_running_processes(self) -> Dict[str, Dict[str, Any]]:
        """Returns details of all active subprocesses."""
        return {
            proc_id: {
                "pid": data["pid"],
                "command": data["command"],
                "vitals": self.get_process_vitals(proc_id),
            }
            for proc_id, data in self._stats.items()
        }


# Global process manager instance
local_process_manager = LocalProcessManager()
