"""
Hardware Router — Wake-on-LAN, termux-notification, device hardware endpoints.
"""

from __future__ import annotations

import asyncio
import socket
import struct
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.logger import get_logger

log = get_logger("router_hardware")
router = APIRouter(prefix="/api/hardware", tags=["Hardware"])


class WakeOnLanRequest(BaseModel):
    mac_address: str
    broadcast_ip: str = "255.255.255.255"
    port: int = 9


class TermuxNotifyRequest(BaseModel):
    title: str
    content: str
    button_text: Optional[str] = None
    button_action: Optional[str] = None


def _send_wol(mac: str, broadcast_ip: str, port: int) -> bool:
    """Send Wake-on-LAN magic packet."""
    try:
        mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
        if len(mac_clean) != 12:
            return False
        mac_bytes = bytes.fromhex(mac_clean)
        magic = b"\xff" * 6 + mac_bytes * 16

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic, (broadcast_ip, port))
        return True
    except Exception as e:
        log.error("wol_failed", error=str(e))
        return False


@router.post("/wake")
async def wake_on_lan(request: WakeOnLanRequest) -> Dict[str, Any]:
    """Send Wake-on-LAN magic packet to a MAC address."""
    success = await asyncio.get_event_loop().run_in_executor(
        None, _send_wol, request.mac_address, request.broadcast_ip, request.port
    )
    if success:
        return {"success": True, "detail": f"WoL packet sent to {request.mac_address}"}
    raise HTTPException(status_code=400, detail=f"Failed to send WoL to {request.mac_address}")


@router.post("/termux-notification")
async def termux_notification(request: TermuxNotifyRequest) -> Dict[str, Any]:
    """Send a Termux notification (Android)."""
    try:
        import subprocess
        cmd = ["termux-notification", "--title", request.title, "--content", request.content]
        if request.button_text and request.button_action:
            cmd.extend(["--button1", request.button_text, "--button1-action", request.button_action])
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "detail": f"Notification sent: {request.title}"}
    except FileNotFoundError:
        log.warning("termux-notification_not_available")
        raise HTTPException(status_code=501, detail="termux-notification not available on this platform")
    except Exception as e:
        log.error("notification_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
