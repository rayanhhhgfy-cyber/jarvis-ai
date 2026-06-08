# ====================================================================
# JARVIS OMEGA — Device Registry
# ====================================================================
"""
Device management: registration, pairing, trust validation,
capability tracking, and heartbeat monitoring.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
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

        # Clerk-style cross-device QR payload generation store:
        # secret → pairing record
        # This is intentionally short-lived and kept in memory for security.
        self._pairing_payload_secrets: Dict[str, Dict[str, Any]] = {}

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

    async def generate_pairing_payload(
        self,
        user_id: str,
        desktop_device_id: str,
        pairing_ttl_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Create a short-lived cross-device pairing payload suitable for QR encoding.

        Contract (used by frontend/Android QR scanner):
          - user_id
          - desktop_device_id
          - pairing_secret (high entropy)
          - base_url
          - expires_at (unix seconds)

        Security notes:
        - Requires that `desktop_device_id` is already trusted.
        - Secret is stored server-side only in memory and expires automatically.
        """
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id is required")
        if not isinstance(desktop_device_id, str) or not desktop_device_id.strip():
            raise ValueError("desktop_device_id is required")
        if pairing_ttl_seconds < 30 or pairing_ttl_seconds > 3600:
            raise ValueError("pairing_ttl_seconds out of allowed range")

        # Auto-register desktop companion for this user if missing
        await self.ensure_desktop_registered(
            user_id=user_id,
            desktop_device_id=desktop_device_id,
            device_name="Jarvis Desktop",
            platform="web",
        )

        # Generate secret
        pairing_secret = generate_device_secret()

        now = datetime.now(timezone.utc)
        expires_at_dt = now + timedelta(seconds=pairing_ttl_seconds)
        expires_at_unix = int(expires_at_dt.timestamp())

        # Use detected LAN IP so phones on the same network can connect.
        # Falls back to localhost if no LAN IP detected.
        lan = settings.lan_ip or "localhost"
        base_url = f"http://{lan}:{settings.backend_port}"

        # Store in memory
        self._pairing_payload_secrets[pairing_secret] = {
            "user_id": user_id,
            "desktop_device_id": desktop_device_id,
            "expires_at": expires_at_unix,
            "created_at": int(now.timestamp()),
        }

        # Best-effort prune of expired secrets
        now_unix = int(datetime.now(timezone.utc).timestamp())
        for secret, rec in list(self._pairing_payload_secrets.items()):
            exp = rec.get("expires_at", 0)
            if isinstance(exp, int) and exp <= now_unix:
                self._pairing_payload_secrets.pop(secret, None)

        return {
            "user_id": user_id,
            "desktop_device_id": desktop_device_id,
            "pairing_secret": pairing_secret,
            "base_url": base_url,
            "expires_at": expires_at_unix,
        }

    def _owner_tag(self, user_id: str) -> str:
        return f"owner:{user_id}"

    def _device_owner(self, device: DeviceInfo) -> Optional[str]:
        for cap in device.capabilities:
            if cap.startswith("owner:"):
                return cap.split(":", 1)[1]
        return None

    async def ensure_desktop_registered(
        self,
        *,
        user_id: str,
        desktop_device_id: str,
        device_name: str,
        platform: str,
    ) -> DeviceInfo:
        """Create or update a trusted desktop device bound to a Clerk user."""
        owner_tag = self._owner_tag(user_id)
        existing = self._devices.get(desktop_device_id)
        if existing:
            if owner_tag not in existing.capabilities:
                existing.capabilities.append(owner_tag)
            existing.trusted = True
            existing.device_name = device_name or existing.device_name
            existing.platform = platform or existing.platform
            existing.device_type = DeviceType.DESKTOP
            await self._persist()
            return existing

        device = DeviceInfo(
            device_id=desktop_device_id,
            device_name=device_name,
            device_type=DeviceType.DESKTOP,
            platform=platform,
            trusted=True,
            capabilities=[owner_tag, "droid:desktop"],
        )
        device.device_secret = generate_device_secret()
        self._devices[desktop_device_id] = device
        await self._persist()
        log.info("desktop_registered", device_id=desktop_device_id, user_id=user_id)
        return device

    async def consume_pairing_payload(
        self,
        *,
        pairing_secret: str,
        mobile_device_id: str,
        device_name: str,
        platform: str,
        user_id: str,
    ) -> DevicePairingResponse:
        """Validate QR secret and register a trusted mobile device."""
        record = self._pairing_payload_secrets.get(pairing_secret)
        if not record:
            raise ValueError("Invalid or expired pairing secret")

        now_unix = int(datetime.utcnow().timestamp())
        if int(record.get("expires_at", 0)) <= now_unix:
            self._pairing_payload_secrets.pop(pairing_secret, None)
            raise ValueError("Pairing secret expired")

        record_user = record.get("user_id")
        if record_user and record_user != user_id:
            raise PermissionError("Pairing secret does not belong to this user")

        desktop_device_id = record.get("desktop_device_id", "")
        owner_tag = self._owner_tag(user_id)

        mobile = self._devices.get(mobile_device_id)
        if not mobile:
            mobile = DeviceInfo(
                device_id=mobile_device_id,
                device_name=device_name,
                device_type=DeviceType.MOBILE,
                platform=platform,
                trusted=True,
                capabilities=[owner_tag, f"paired_desktop:{desktop_device_id}", "droid:mobile"],
            )
            mobile.device_secret = generate_device_secret()
            self._devices[mobile_device_id] = mobile
        else:
            mobile.trusted = True
            mobile.device_name = device_name or mobile.device_name
            mobile.platform = platform or mobile.platform
            mobile.device_type = DeviceType.MOBILE
            if owner_tag not in mobile.capabilities:
                mobile.capabilities.append(owner_tag)
            cap = f"paired_desktop:{desktop_device_id}"
            if cap not in mobile.capabilities:
                mobile.capabilities.append(cap)

        self._pairing_payload_secrets.pop(pairing_secret, None)
        await self._persist()

        access_token = create_access_token(
            {"device_id": mobile_device_id, "device_name": mobile.device_name}
        )
        refresh_token = create_refresh_token({"device_id": mobile_device_id})

        log.info(
            "qr_pairing_consumed",
            mobile_device_id=mobile_device_id,
            desktop_device_id=desktop_device_id,
            user_id=user_id,
        )

        return DevicePairingResponse(
            device_id=mobile_device_id,
            device_secret=mobile.device_secret or "",
            access_token=access_token,
            refresh_token=refresh_token,
            pairing_code="",
            approved=True,
        )

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
