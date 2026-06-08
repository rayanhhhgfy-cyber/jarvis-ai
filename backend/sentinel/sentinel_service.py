from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any

import psutil
import httpx

from shared.logger import get_logger

log = get_logger("sentinel_service")


class SentinelService:
    """
    Proactive Sentinel — monitors system health, detects crashes,
    and executes auto-fix routines without human intervention.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = 30
        self._last_fix_results: List[Dict[str, Any]] = []
        self._backend_port = 8000

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._sentinel_loop())
        log.info("sentinel_started", interval=self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("sentinel_stopped")

    async def _sentinel_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                issues = await self._check_all()
                for issue in issues:
                    await self._auto_fix(issue)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("sentinel_loop_error", error=str(e))

    async def _check_all(self) -> List[Dict[str, Any]]:
        issues = []

        vitals = self._check_system_vitals()
        if vitals:
            issues.append(vitals)

        backend_issue = await self._check_backend_health()
        if backend_issue:
            issues.append(backend_issue)

        dep_issue = await self._check_dependency_health()
        if dep_issue:
            issues.append(dep_issue)

        return issues

    def _check_system_vitals(self) -> Optional[Dict[str, Any]]:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        if cpu > 95:
            return {"type": "high_cpu", "value": cpu, "message": f"CPU at {cpu}%"}
        if mem.percent > 90:
            return {"type": "high_memory", "value": mem.percent, "message": f"Memory at {mem.percent}%"}
        return None

    async def _check_backend_health(self) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"http://localhost:{self._backend_port}/health")
                if r.status_code != 200:
                    return {"type": "backend_down", "message": "Backend health check failed", "status_code": r.status_code}
                return None
        except Exception:
            return {"type": "backend_down", "message": "Backend unreachable"}

    async def _check_dependency_health(self) -> Optional[Dict[str, Any]]:
        try:
            # Skip ChromaDB import to prevent telemetry crashes
            # import chromadb
            import fastapi
            import httpx
            import psutil
            import edge_tts
            return None
        except ImportError as e:
            return {"type": "missing_dependency", "message": f"Missing: {e.name}"}

    async def _auto_fix(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        log.warning("auto_fix_attempting", issue=issue["type"], message=issue.get("message"))
        result = {"issue": issue["type"], "success": False, "action": "", "timestamp": datetime.utcnow().isoformat()}

        try:
            if issue["type"] == "high_cpu":
                result["action"] = "killing_top_process"
                await self._kill_top_cpu_process()
                result["success"] = True

            elif issue["type"] == "high_memory":
                result["action"] = "clearing_temp_files"
                self._clear_temp_files()
                result["success"] = True

            elif issue["type"] == "backend_down":
                result["action"] = "restarting_backend"
                success = await self._restart_backend()
                result["success"] = success

            elif issue["type"] == "missing_dependency":
                dep_name = issue.get("message", "").replace("Missing: ", "")
                result["action"] = f"installing_{dep_name}"
                success = await self._install_dependency(dep_name)
                result["success"] = success

        except Exception as e:
            log.error("auto_fix_failed", issue=issue["type"], error=str(e))

        self._last_fix_results.append(result)
        if len(self._last_fix_results) > 100:
            self._last_fix_results = self._last_fix_results[-100:]

        if result["success"]:
            log.info("auto_fix_success", issue=issue["type"], action=result["action"])
        else:
            log.error("auto_fix_failed_escalate", issue=issue["type"])
        return result

    async def _kill_top_cpu_process(self) -> None:
        try:
            procs = sorted(psutil.process_iter(["pid", "name", "cpu_percent"]),
                           key=lambda p: p.info["cpu_percent"] or 0, reverse=True)
            for proc in procs[:3]:
                if proc.info["cpu_percent"] and proc.info["cpu_percent"] > 50:
                    if proc.info["name"] not in ("System", "Idle"):
                        proc.terminate()
                        log.info("terminated_high_cpu_process", name=proc.info["name"], pid=proc.info["pid"])
        except Exception as e:
            log.error("kill_top_cpu_failed", error=str(e))

    def _clear_temp_files(self) -> None:
        import tempfile
        try:
            temp_dir = tempfile.gettempdir()
            for f in os.listdir(temp_dir):
                if f.startswith("tmp") or f.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(temp_dir, f))
                    except Exception:
                        pass
        except Exception as e:
            log.error("clear_temp_failed", error=str(e))

    async def _restart_backend(self) -> bool:
        try:
            subprocess.Popen(["python", "-m", "uvicorn", "backend.main:app",
                              "--host", "0.0.0.0", "--port", str(self._backend_port),
                              "--reload"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True
        except Exception as e:
            log.error("restart_backend_failed", error=str(e))
            return False

    async def _install_dependency(self, dep_name: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pip", "install", dep_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            log.error("install_dep_failed", dep=dep_name, error=str(e))
            return False

    def get_fix_history(self) -> List[Dict[str, Any]]:
        return self._last_fix_results


sentinel_service = SentinelService()
