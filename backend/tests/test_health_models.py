# ====================================================================
# JARVIS OMEGA — Health Snapshot Model Test
# ====================================================================
"""
Phase 3 regression: ``GET /health`` returns a typed ``HealthSnapshot`` model.
"""

from __future__ import annotations

from shared.models import HealthSnapshot, VitalsSnapshot
from shared.constants import HealthState


def test_health_snapshot_defaults():
    h = HealthSnapshot()
    assert h.status == "online"
    assert h.health is HealthState.HEALTHY
    assert h.scheduler_active is False
    assert h.active_connections == 0
    assert h.tasks_in_queue == 0


def test_health_snapshot_construction():
    h = HealthSnapshot(
        status="online",
        health=HealthState.DEGRADED,
        scheduler_active=True,
        active_connections=2,
        tasks_in_queue=5,
    )
    assert h.health is HealthState.DEGRADED
    assert h.active_connections == 2
    # Pydantic v2: serializable to dict with model_dump.
    d = h.model_dump()
    assert d["scheduler_active"] is True


def test_vitals_snapshot_defaults():
    v = VitalsSnapshot()
    assert v.cpu_percent == 0.0
    assert v.memory_percent == 0.0
    assert v.disk_percent == 0.0
    assert v.health_state is HealthState.HEALTHY
