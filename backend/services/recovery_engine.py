"""
Recovery Engine — self-healing debug loop and supply-chain vulnerability watchdog.

# pip install: httpx
# NVD API: free unauthenticated tier (rate-limited)
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from shared.logger import get_logger

log = get_logger("recovery_engine")


# =========================================================================
# DATA TYPES
# =========================================================================


@dataclass
class DebugAndRetryPayload:
    exception: Exception
    stack_trace: str
    source: str = ""
    attempt: int = 0
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CVEReport:
    cve_id: str
    description: str
    cvss_score: float
    severity: str
    affected_packages: List[str] = field(default_factory=list)
    remediation: str = ""


# =========================================================================
# AUTO-DEBUG LOOP
# =========================================================================


class AutoDebugLoop:
    """
    3-turn retry loop with exponential backoff.
    Wraps subprocess/async exceptions and retries with escalating delays.
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._backoff_times = [1, 4, 9]  # 1s → 4s → 9s

    async def execute(self, payload: DebugAndRetryPayload, coro_factory) -> Any:
        """
        Execute a coroutine with retry logic.

        Args:
            payload: Debug context from the failed attempt
            coro_factory: Async callable that returns the operation result
        Returns:
            Successful result or raises after max retries
        """
        last_error = payload.exception

        for attempt in range(payload.attempt, self.max_retries):
            try:
                return await coro_factory()
            except Exception as e:
                last_error = e
                backoff = self._backoff_times[attempt] if attempt < len(self._backoff_times) else 10
                log.warning(
                    "debug_retry",
                    attempt=attempt + 1,
                    max=self.max_retries,
                    backoff=backoff,
                    error=str(e)[:100],
                )
                try:
                    from backend.services.sound_engine import sound_engine, JarvisEvent
                    await sound_engine.jarvis_alert(JarvisEvent.DEBUG_RETRY)
                except Exception:
                    pass
                await asyncio.sleep(backoff)

        try:
            from backend.services.sound_engine import sound_engine, JarvisEvent
            await sound_engine.jarvis_alert(JarvisEvent.DEBUG_FAILED)
        except Exception:
            pass
        raise last_error


# =========================================================================
# SUPPLY-CHAIN VULNERABILITY WATCHDOG
# =========================================================================


class SupplyChainWatchdog:
    """
    Checks installed packages against the NVD database.
    Uses free unauthenticated tier (rate-limited to ~5 reqs / 30s).
    """

    NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self._cache: Dict[str, List[CVEReport]] = {}

    async def check_package(self, package_name: str, version: str) -> List[CVEReport]:
        """Query NVD for known vulnerabilities in a package."""
        cache_key = f"{package_name}@{version}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        results: List[CVEReport] = []
        try:
            resp = await self._http.get(
                self.NVD_API_BASE,
                params={
                    "keywordSearch": f"{package_name} {version}",
                    "resultsPerPage": 10,
                },
                headers={"User-Agent": "JARVIS-Omega/1.0"},
            )
            if resp.status_code != 200:
                log.warning("nvd_api_error", status=resp.status_code)
                return results

            data = resp.json()
            for vuln in data.get("vulnerabilities", []):
                cve = vuln.get("cve", {})
                metrics = cve.get("metrics", {})
                cvss_v3 = metrics.get("cvssMetricV31", [{}])[0].get("cvssData", {})
                cvss_score = cvss_v3.get("baseScore", 0.0)

                report = CVEReport(
                    cve_id=cve.get("id", "UNKNOWN"),
                    description=cve.get("descriptions", [{}])[0].get("value", "")[:300],
                    cvss_score=cvss_score,
                    severity=cvss_v3.get("baseSeverity", "UNKNOWN"),
                    affected_packages=[package_name],
                    remediation=f"Update {package_name} to the latest version",
                )
                # Alert on high/critical
                if cvss_score >= 7.0:
                    try:
                        from backend.services.sound_engine import sound_engine, JarvisEvent
                        await sound_engine.jarvis_alert(JarvisEvent.VULNERABILITY_DETECTED)
                    except Exception:
                        pass
                    log.warning("vulnerability_detected", cve=report.cve_id, score=cvss_score, package=package_name)

                results.append(report)

        except Exception as e:
            log.error("nvd_query_failed", package=package_name, error=str(e))

        self._cache[cache_key] = results
        return results

    async def check_installed_packages(self) -> List[CVEReport]:
        """Check all installed pip packages against NVD."""
        all_reports: List[CVEReport] = []
        try:
            proc = subprocess.run(
                ["pip", "list", "--format=freeze"],
                capture_output=True, text=True, timeout=30,
            )
            for line in proc.stdout.strip().split("\n"):
                if "==" in line:
                    name, ver = line.split("==", 1)
                    reports = await self.check_package(name.strip(), ver.strip())
                    all_reports.extend(reports)
        except Exception as e:
            log.error("package_list_failed", error=str(e))
        return all_reports

    async def close(self):
        await self._http.aclose()


# Global instances
auto_debug = AutoDebugLoop()
supply_chain_watchdog = SupplyChainWatchdog()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.recovery_engine import auto_debug, DebugAndRetryPayload
# payload = DebugAndRetryPayload(exception=ValueError("test"), stack_trace="...", source="test")
# result = await auto_debug.execute(payload, lambda: some_async_operation())
# ---
