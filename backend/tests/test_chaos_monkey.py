# ====================================================================
# JARVIS OMEGA — Chaos Monkey Service Unit Tests
# ====================================================================
"""
Unit tests for the Chaos Monkey service, verifying synthetic failure simulations and reports.
"""

import os
import pytest
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.chaos_monkey import ChaosMonkeyService

TEST_STORAGE_DIR = Path("./storage/test_chaos_temp")

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def chaos_service():
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)
    TEST_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Force enable and override path
    with patch.dict(os.environ, {"CHAOS_MONKEY_ENABLED": "True"}):
        with patch("backend.services.chaos_monkey.REPORTS_PATH", TEST_STORAGE_DIR / "chaos_reports.json"):
            service = ChaosMonkeyService()
            yield service

    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)

def test_disabled_by_default():
    """Verify service respects the CHAOS_MONKEY_ENABLED env var."""
    with patch.dict(os.environ, {"CHAOS_MONKEY_ENABLED": "False"}):
        service = ChaosMonkeyService()
        assert service.enabled is False

@pytest.mark.anyio
async def test_trigger_cpu_spike(chaos_service):
    """Test CPU spike execution."""
    res = await chaos_service.trigger_cpu_spike(duration_seconds=1)
    assert res["success"] is True
    assert "spike completed" in res["message"]

@pytest.mark.anyio
async def test_trigger_memory_spike(chaos_service):
    """Test memory spike execution with small size to avoid actual OOM/delay."""
    res = await chaos_service.trigger_memory_spike(size_mb=1, duration_seconds=1)
    assert res["success"] is True
    assert "spike of 1MB completed" in res["message"]

@pytest.mark.anyio
async def test_simulate_network_timeout(chaos_service):
    """Test injected latency delay."""
    res = await chaos_service.simulate_network_timeout(latency_seconds=0.1)
    assert res["success"] is True
    assert "delay of 0.1s completed" in res["message"]

@pytest.mark.anyio
@patch("backend.scheduler.scheduler")
async def test_simulate_scheduler_crash(mock_scheduler, chaos_service):
    """Test simulated scheduler crash and recovery."""
    mock_inner = MagicMock()
    mock_inner.running = True
    mock_scheduler._scheduler = mock_inner
    
    res = await chaos_service.simulate_scheduler_crash()
    assert res["success"] is True
    assert "recovered successfully" in res["message"]
    
    mock_inner.shutdown.assert_called_once()
    mock_inner.start.assert_called_once()

@pytest.mark.anyio
@patch("backend.scheduler.scheduler")
async def test_weekly_chaos_test(mock_scheduler, chaos_service):
    """Test running the aggregated weekly chaos test report creation."""
    mock_inner = MagicMock()
    mock_inner.running = True
    mock_scheduler._scheduler = mock_inner
    
    # We patch triggers to make weekly test fast
    with patch.object(chaos_service, "trigger_cpu_spike", AsyncMock(return_value={"success": True, "message": "CPU spike completed"})) as m_cpu:
        with patch.object(chaos_service, "trigger_memory_spike", AsyncMock(return_value={"success": True, "message": "Memory spike completed"})) as m_mem:
            with patch.object(chaos_service, "simulate_scheduler_crash", AsyncMock(return_value={"success": True, "message": "Scheduler recovered"})) as m_sched:
                report = await chaos_service.run_weekly_chaos_test()
                
                assert report["overall_status"] == "STABLE"
                assert report["tests_run"] == 3
                assert report["tests_passed"] == 3
                assert len(chaos_service.get_report_history()) == 1
                
                m_cpu.assert_called_once_with(duration_seconds=3)
                m_mem.assert_called_once_with(size_mb=80, duration_seconds=2)
                m_sched.assert_called_once()
