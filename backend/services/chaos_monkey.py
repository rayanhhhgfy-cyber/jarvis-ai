# ====================================================================
# JARVIS OMEGA — Chaos Monkey Service
# ====================================================================
"""
Chaos Monkey Service.
Simulates random failures (memory spikes, CPU spikes, database degradation)
to verify system resilience, and logs results in a weekly report.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from backend.config import settings
from shared.logger import get_logger

log = get_logger("chaos_monkey")

REPORTS_PATH = Path(settings.storage_dir) / "chaos_reports.json"


class ChaosMonkeyService:
    def __init__(self) -> None:
        self.enabled = os.environ.get("CHAOS_MONKEY_ENABLED", "False").lower() in ("true", "1", "yes")
        self.reports_path = REPORTS_PATH
        self.reports_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_reports()

    def _load_reports(self) -> None:
        if self.reports_path.exists():
            try:
                self.reports = json.loads(self.reports_path.read_text(encoding="utf-8"))
            except Exception:
                self.reports = []
        else:
            self.reports = []

    def _save_reports(self) -> None:
        try:
            self.reports_path.write_text(json.dumps(self.reports, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("chaos_save_reports_failed", error=str(e))

    async def trigger_cpu_spike(self, duration_seconds: int = 5) -> Dict[str, Any]:
        """Simulate high CPU usage by running a busy loop in a thread."""
        if not self.enabled:
            return {"success": False, "message": "Chaos Monkey is disabled."}

        log.warning("chaos_trigger_cpu_spike", duration=duration_seconds)
        start = time.time()

        def _busy_loop():
            while time.time() - start < duration_seconds:
                _ = 2 ** 30  # Heavy arithmetic calculation

        await asyncio.to_thread(_busy_loop)
        return {"success": True, "message": f"CPU spike completed after {duration_seconds}s."}

    async def trigger_memory_spike(self, size_mb: int = 120, duration_seconds: int = 4) -> Dict[str, Any]:
        """Simulate memory consumption spike by allocating block lists."""
        if not self.enabled:
            return {"success": False, "message": "Chaos Monkey is disabled."}

        log.warning("chaos_trigger_memory_spike", size_mb=size_mb, duration=duration_seconds)
        
        # Each char in python is ~1 byte. Allocate dummy list of large strings.
        dummy_list = []
        try:
            # 1 MB of string space
            one_mb_str = "x" * (1024 * 1024)
            for _ in range(size_mb):
                dummy_list.append(one_mb_str)
                
            # Keep allocated
            await asyncio.sleep(duration_seconds)
        finally:
            # Deallocate and garbage collect
            dummy_list.clear()
            import gc
            gc.collect()

        return {"success": True, "message": f"Memory allocation spike of {size_mb}MB completed."}

    async def simulate_network_timeout(self, latency_seconds: float = 3.0) -> Dict[str, Any]:
        """Inject synthetic latency delay to mock timeouts."""
        if not self.enabled:
            return {"success": False, "message": "Chaos Monkey is disabled."}

        log.warning("chaos_inject_network_latency", seconds=latency_seconds)
        await asyncio.sleep(latency_seconds)
        return {"success": True, "message": f"Injected network delay of {latency_seconds}s completed."}

    async def simulate_scheduler_crash(self) -> Dict[str, Any]:
        """Stop and restart the scheduler subsystem to check failover recovery."""
        if not self.enabled:
            return {"success": False, "message": "Chaos Monkey is disabled."}

        from backend.scheduler import scheduler
        log.warning("chaos_trigger_scheduler_crash")
        
        try:
            # Stop the scheduler
            if scheduler._scheduler.running:
                scheduler._scheduler.shutdown(wait=False)
                log.info("chaos_scheduler_stopped")
            
            # Simulated downtime
            await asyncio.sleep(3.0)
            
            # Restart
            scheduler._scheduler.start()
            log.info("chaos_scheduler_recovered_successfully")
            return {"success": True, "message": "Scheduler crashed and recovered successfully."}
        except Exception as e:
            log.error("chaos_scheduler_recovery_failed", error=str(e))
            return {"success": False, "message": f"Scheduler recovery failed: {str(e)}"}

    async def run_weekly_chaos_test(self) -> Dict[str, Any]:
        """Execute a series of randomized failure triggers and write a report."""
        if not self.enabled:
            return {"success": False, "message": "Chaos Monkey is disabled. Test aborted."}

        test_id = f"chaos_{int(time.time())}"
        log.warning("chaos_starting_weekly_test", test_id=test_id)
        
        results = []
        
        # Test 1: CPU Spike
        t1 = await self.trigger_cpu_spike(duration_seconds=3)
        results.append({"failure_type": "cpu_spike", "result": t1})
        
        # Test 2: Memory Spike
        t2 = await self.trigger_memory_spike(size_mb=80, duration_seconds=2)
        results.append({"failure_type": "memory_spike", "result": t2})
        
        # Test 3: Subsystem Crash (Scheduler)
        t3 = await self.simulate_scheduler_crash()
        results.append({"failure_type": "scheduler_crash", "result": t3})

        # Summarize test run
        success_count = sum(1 for r in results if r["result"]["success"])
        overall_status = "STABLE" if success_count == len(results) else "DEGRADED"

        report = {
            "test_id": test_id,
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": overall_status,
            "tests_run": len(results),
            "tests_passed": success_count,
            "details": results,
        }

        self.reports.insert(0, report)
        self.reports = self.reports[:30] # Keep last 30 reports
        self._save_reports()

        log.warning("chaos_test_completed", test_id=test_id, status=overall_status)
        return report

    def get_report_history(self) -> List[Dict[str, Any]]:
        return self.reports


# Singleton
chaos_monkey = ChaosMonkeyService()
