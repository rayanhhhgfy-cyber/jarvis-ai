# ====================================================================
# JARVIS OMEGA — Device Registry Tests
# ====================================================================
"""
Phase 1 regression tests for the device registry.

Covers pairing flow + trust persistence (the bug that caused the WebSocket
403 storm).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.device_registry import DeviceRegistry
from shared.constants import DeviceType
from shared.models import DevicePairingRequest


@pytest.fixture
def registry(tmp_path: Path) -> DeviceRegistry:
    return DeviceRegistry(storage_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_initiate_pairing_returns_untrusted_device(registry: DeviceRegistry):
    req = DevicePairingRequest(
        device_name="Sir's Workstation",
        device_type=DeviceType.DESKTOP,
        platform="win32",
    )
    resp = await registry.initiate_pairing(req)
    assert resp.approved is False
    assert resp.device_secret
    assert resp.pairing_code
    assert resp.access_token == ""  # only issued after approval


@pytest.mark.asyncio
async def test_approve_pairing_marks_trusted_and_issues_tokens(registry: DeviceRegistry):
    req = DevicePairingRequest(
        device_name="Workstation",
        device_type=DeviceType.DESKTOP,
        platform="linux",
    )
    resp = await registry.initiate_pairing(req)
    approved = await registry.approve_pairing(resp.pairing_code)
    assert approved is not None
    assert approved.approved is True
    assert approved.access_token
    assert approved.refresh_token

    # is_trusted should reflect the new state
    assert registry.is_trusted(resp.device_id) is True


@pytest.mark.asyncio
async def test_persistence_round_trip(registry: DeviceRegistry):
    """Approved trust must survive a registry reload (the WS 403 root cause)."""
    req = DevicePairingRequest(
        device_name="Workstation",
        device_type=DeviceType.DESKTOP,
        platform="win32",
    )
    resp = await registry.initiate_pairing(req)
    await registry.approve_pairing(resp.pairing_code)

    # Storage file must exist and contain trusted=True.
    persist_path = Path(registry._storage_path)
    assert persist_path.exists()
    saved = persist_path.read_text(encoding="utf-8")
    assert '"trusted": true' in saved

    # Simulate a restart: new registry instance pointing at the same file.
    restarted = DeviceRegistry(storage_dir=str(persist_path.parent))
    await restarted.initialize()
    assert restarted.is_trusted(resp.device_id) is True


@pytest.mark.asyncio
async def test_invalid_pairing_code_returns_none(registry: DeviceRegistry):
    result = await registry.approve_pairing("000000")
    assert result is None


@pytest.mark.asyncio
async def test_is_trusted_unknown_device(registry: DeviceRegistry):
    assert registry.is_trusted("nonexistent-device-id") is False
