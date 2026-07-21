# ====================================================================
# JARVIS OMEGA — Device Registry
# ====================================================================
"""
Device management: registration, pairing, trust validation,
capability tracking, and heartbeat monitoring.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import DeviceType, EventType
from shared.logger import get_logger
from shared.models import DeviceInfo, DevicePairingRequest, DevicePairingResponse
from shared.security import (
    create_access_token,
    create_device_token,
    create_refresh_token,
    generate_device_secret,
    generate_pairing_code,
)

log = get_logger("device_registry")


class DeviceRegistry:
    """
    Manages device registration, pairing, and trust relationships.
    New devices must go through the pairing flow before being trusted.
    """

    def __init__(self, storage_dir: str = "./storage") -> None:
        self._devices: Dict[str, DeviceInfo] = {}
        self._pairing_codes: Dict[str, str] = {}  # code → device_id
        self._storage_path = Path(storage_dir) / "devices.json"
        self._event_bus = None

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    async def initialize(self) -> None:
        """Load persisted devices from disk."""
        if self._storage_path.exists():
            try:
                data = json.loads(self._storage_path.read_text(encoding="utf-8"))
                for d in data:
                    device = DeviceInfo(**d)
                    device.online = False
                    self._devices[device.device_id] = device
                log.info("devices_loaded", count=len(self._devices))
            except Exception as e:
                log.error("device_load_error", error=str(e))

    async def _persist(self) -> None:
        """Save devices to disk."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [d.model_dump(mode="json") for d in self._devices.values()]
        self._storage_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    async def initiate_pairing(self, request: DevicePairingRequest) -> DevicePairingResponse:
        """Start the pairing process for a new device."""
        device = DeviceInfo(
            device_name=request.device_name,
            device_type=request.device_type,
            platform=request.platform,
            trusted=False,
        )
        secret = generate_device_secret()
        device.device_secret = secret
        code = generate_pairing_code()

        self._devices[device.device_id] = device
        self._pairing_codes[code] = device.device_id

        log.info(
            "pairing_initiated",
            device_id=device.device_id,
            device_name=device.device_name,
            pairing_code=code,
        )

        return DevicePairingResponse(
            device_id=device.device_id,
            device_secret=secret,
            access_token="",
            refresh_token="",
            pairing_code=code,
            approved=False,
        )

    async def approve_pairing(self, pairing_code: str) -> Optional[DevicePairingResponse]:
        """Sir approves a device pairing."""
        device_id = self._pairing_codes.get(pairing_code)
        if not device_id:
            log.warning("pairing_invalid_code", code=pairing_code)
            return None

        device = self._devices.get(device_id)
        if not device:
            return None

        device.trusted = True
        device.registered_at = datetime.utcnow()

        access_token = create_access_token({"device_id": device_id, "device_name": device.device_name})
        refresh_token = create_refresh_token({"device_id": device_id})

        self._pairing_codes.pop(pairing_code, None)
        await self._persist()

        log.info("pairing_approved", device_id=device_id, device_name=device.device_name)

        if self._event_bus:
            await self._event_bus.publish(
                EventType.DEVICE_PAIRED,
                {"device_id": device_id, "device_name": device.device_name},
            )

        return DevicePairingResponse(
            device_id=device_id,
            device_secret=device.device_secret or "",
            access_token=access_token,
            refresh_token=refresh_token,
            pairing_code=pairing_code,
            approved=True,
        )

    def is_trusted(self, device_id: str) -> bool:
        """Check if a device is trusted."""
        device = self._devices.get(device_id)
        return device is not None and device.trusted

    async def update_status(
        self,
        device_id: str,
        online: bool = True,
        ip_address: str = "",
        latency_ms: float = 0.0,
        battery_level: Optional[float] = None,
        is_charging: Optional[bool] = None,
    ) -> None:
        """Update a device's status."""
        device = self._devices.get(device_id)
        if not device:
            return

        device.online = online
        device.last_seen = datetime.utcnow()
        if ip_address:
            device.ip_address = ip_address
        device.latency_ms = latency_ms
        if battery_level is not None:
            device.battery_level = battery_level
        if is_charging is not None:
            device.is_charging = is_charging

    async def remove_device(self, device_id: str) -> bool:
        """Remove a device from the registry."""
        device = self._devices.pop(device_id, None)
        if device:
            await self._persist()
            log.info("device_removed", device_id=device_id)
            return True
        return False

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get a device by ID."""
        return self._devices.get(device_id)

    def get_all_devices(self) -> List[DeviceInfo]:
        """Get all registered devices."""
        return list(self._devices.values())

    def get_online_devices(self) -> List[DeviceInfo]:
        """Get all currently online devices."""
        return [d for d in self._devices.values() if d.online]


# Global device registry instance
device_registry = DeviceRegistry()
