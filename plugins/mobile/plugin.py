# ====================================================================
# JARVIS OMEGA — Mobile Plugin (Android via ADB)
# ====================================================================
"""
Phase 8 seed plugin: control an Android device via ADB.

Requirements:
  * ``adb`` on PATH (Android Platform Tools)
  * Device connected via USB or wireless ADB with developer mode + USB
    debugging enabled.

All tools fail gracefully with a clear message if adb is missing or no
device is attached.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from backend.tools import tool, RiskTier


async def _adb(args: list[str], timeout: float = 10.0) -> Dict[str, Any]:
    """Run an adb subcommand and return its captured output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return {"ok": False, "error": f"adb timed out after {timeout}s"}
        rc = proc.returncode or 0
        out_s = out.decode("utf-8", errors="replace")
        err_s = err.decode("utf-8", errors="replace")
        if rc != 0:
            return {"ok": False, "exit_code": rc, "stderr": err_s}
        return {"ok": True, "exit_code": rc, "stdout": out_s, "stderr": err_s}
    except FileNotFoundError:
        return {"ok": False, "error": "adb executable not found on PATH — install Android Platform Tools"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="adb.devices",
    description="List connected Android devices via ``adb devices``.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="mobile",
)
async def adb_devices() -> Dict[str, Any]:
    return await _adb(["devices"])


@tool(
    name="adb.screenshot",
    description="Capture a screenshot from the attached Android device. Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "device": {"type": "string", "description": "Optional device serial for multiple devices."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="mobile",
)
async def adb_screenshot(device: str = "") -> Dict[str, Any]:
    import base64
    args = ["-s", device] if device else []
    # Pull screenshot bytes via adb exec-out (binary-safe).
    res = await _adb(args + ["exec-out", "screencap", "-p"], timeout=15)
    if not res.get("ok"):
        return res
    # exec-out stdout goes through asyncio capture; re-encoded here.
    proc = await asyncio.create_subprocess_exec(
        "adb", *args, "exec-out", "screencap", "-p",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return {"ok": True, "image_base64": base64.b64encode(out).decode("ascii"), "bytes": len(out)}


@tool(
    name="adb.tap",
    description="Tap the screen at (x, y).",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "device": {"type": "string", "default": ""},
        },
        "required": ["x", "y"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="mobile",
)
async def adb_tap(x: int, y: int, device: str = "") -> Dict[str, Any]:
    args = ["-s", device] if device else []
    return await _adb(args + ["shell", "input", "tap", str(x), str(y)])


@tool(
    name="adb.swipe",
    description="Swipe from (x1, y1) to (x2, y2) over duration_ms.",
    parameters={
        "type": "object",
        "properties": {
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"},
            "duration_ms": {"type": "integer", "default": 300},
            "device": {"type": "string", "default": ""},
        },
        "required": ["x1", "y1", "x2", "y2"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="mobile",
)
async def adb_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, device: str = "") -> Dict[str, Any]:
    args = ["-s", device] if device else []
    return await _adb(args + ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])


@tool(
    name="adb.launch",
    description="Launch an app by package name (e.g. com.twitter.android).",
    parameters={
        "type": "object",
        "properties": {
            "package": {"type": "string"},
            "device": {"type": "string", "default": ""},
        },
        "required": ["package"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="mobile",
)
async def adb_launch(package: str, device: str = "") -> Dict[str, Any]:
    args = ["-s", device] if device else []
    return await _adb(args + ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])


@tool(
    name="adb.shell",
    description="Run an arbitrary shell command on the device via adb shell. Use sparingly.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "device": {"type": "string", "default": ""},
        },
        "required": ["command"],
    },
    risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    category="mobile",
)
async def adb_shell(command: str, device: str = "") -> Dict[str, Any]:
    args = ["-s", device] if device else []
    return await _adb(args + ["shell", command])


PLUGIN_NAME = "mobile"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Android device control via ADB (screenshot, tap, swipe, launch, shell)."
