# ====================================================================
# JARVIS OMEGA — Chat Router
# ====================================================================
"""
REST endpoints for processing natural language dialog from Sir. Integrates
with the command interpreter for device control, the MythoMax reasoning
engine for conversation, and pushes proactive task reports via WebSocket.
"""

from __future__ import annotations

import base64
import os
import re
import traceback
import asyncio
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends, status

from shared.models import ChatRequest, ChatResponse, MemoryEntry, TaskDefinition
from shared.constants import MemoryCategory, AgentType, TaskStatus
from backend.services.llm_service import llm_service
from backend.services.tts_service import tts_service
from backend.services.memory_service import memory_service
from backend.services.command_interpreter import command_interpreter
from backend.services.browser_service import browser_service
from backend.task_manager import task_manager
from shared.logger import get_logger
from shared.constants import DeviceType
from backend.droid.device_manager import droid_device_manager
from backend.websocket_manager import ws_manager
from backend.services.desktop_service import desktop_service
from backend.services.desktop_cursor import cursor_overlay
from backend.services.media_generation_service import generate_image as svc_generate_image, generate_video as svc_generate_video
from backend.services.web_search_service import web_search_service
from backend.services.excel_service import excel_service
from backend.services.file_download_service import file_download_service
from local_client.agents import orchestrator as agent_orchestrator

log = get_logger("router_chat")
router = APIRouter(prefix="/api/chat", tags=["Chat"])

# Simple in-memory list for short term dialogue history tracking
dialogue_history: List[dict] = []

# Commands matching these keywords get routed through Playwright browser
# instead of shell `start "" "URL"` so JARVIS can log in, navigate, and interact.
BROWSER_ELIGIBLE = [
    "instagram", "messenger", "facebook", "youtube", "google",
    "twitter", "reddit", "linkedin", "gmail", "github", "chatgpt",
    "netflix", "twitch", "amazon",
]


def _pick_first_connected_device_id(target_types: list[DeviceType]) -> str | None:
    devices = ws_manager.get_connected_devices()
    target_values = {t.value for t in target_types}
    for d in devices:
        if d.get("device_type") in target_values and d.get("device_id"):
            return d["device_id"]
    return None

async def _dispatch_droid_command_and_wait(
    *,
    user_id: str | None,
    target_device_type: DeviceType,
    cmd: str,
    payload: dict[str, object],
    timeout_seconds: float = 30.0,
) -> dict:
    target_device_id = _pick_first_connected_device_id([target_device_type])
    if not target_device_id:
        return {
            "completed": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"No connected device available for type={target_device_type.value}",
            "task_id": "droid-dispatch",
        }

    try:
        raw_result = await droid_device_manager.send_command_and_wait(
            user_id=user_id,
            target_device_id=target_device_id,
            cmd=cmd,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        ok = bool(raw_result.get("ok"))
        return {
            "completed": True,
            "exit_code": 0 if ok else 1,
            "stdout": (raw_result.get("data") or {}).get("output") or (raw_result.get("data") or raw_result),
            "stderr": raw_result.get("error") or "" if ok else (raw_result.get("error") or "Unknown droid error"),
            "task_id": "droid-dispatch",
        }
    except TimeoutError as te:
        return {
            "completed": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(te),
            "task_id": "droid-dispatch",
        }
    except Exception as e:
        return {
            "completed": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "task_id": "droid-dispatch",
        }

async def _dispatch_and_wait(cmd: str, description: str, timeout: float = 15.0) -> dict:
    """
    Executes an OS command DIRECTLY via subprocess on this machine.
    No daemon WebSocket needed — guaranteed real execution.
    """
    import subprocess

    log.info("executing_command_directly", command=cmd, description=description)
    loop = asyncio.get_running_loop()

    # Phase 1 — try with PIPE in a thread (works for console commands)
    def _try_pipe():
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return None  # GUI app indicator

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        is_gui = (
            exit_code != 0 and not stdout and not stderr
        ) or (
            exit_code != 0 and (
                "Input redirection" in stderr
                or "not supported" in stderr
            )
        )
        if is_gui:
            return None

        return {
            "completed": True,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "task_id": "direct-exec",
        }

    result = await loop.run_in_executor(None, _try_pipe)
    if result is not None:
        return result

    # Phase 2 — likely a GUI app, fire-and-forget without PIPE
    log.info("gui_app_detected_launching_detached", command=cmd)
    try:
        subprocess.Popen(cmd, shell=True)
    except Exception:
        pass
    return {
        "completed": True,
        "exit_code": 0,
        "stdout": "Application launched successfully.",
        "stderr": "",
        "task_id": "direct-exec",
    }


async def _handle_desktop_command(cmd: str, prefix: str = "desktop") -> dict:
    """
    Execute a desktop_<action> command through DesktopService.
    Shows visual cursor overlay automatically for mouse/keyboard actions.
    Both Phase 1 (interpreter) and Phase 3 (LLM) call this — zero duplication.
    """
    if not cmd.startswith("desktop_"):
        return {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Not a desktop command: {cmd}", "task_id": f"{prefix}-err"}

    parts = cmd.split("|")
    action = parts[0][len("desktop_"):]
    args = parts[1:] if len(parts) > 1 else []
    task_id = f"{prefix}-{action}"

    try:
        # ---- Mouse ----
        if action == "mouse_move":
            if len(args) >= 2:
                x, y = int(args[0]), int(args[1])
                dur = float(args[2]) if len(args) > 2 else 0.3
                cursor_overlay.start()
                cursor_overlay.show(x, y, "#00FF00", "Move")
                return _result(await desktop_service.move_mouse(x, y, dur), f"Moved mouse to ({x}, {y})", task_id)
            return _result({"success": False, "error": "Need x y coordinates"}, "", task_id)

        elif action == "click":
            if len(args) >= 2:
                x, y = int(args[0]), int(args[1])
                btn = args[2] if len(args) > 2 else "left"
                cursor_overlay.start()
                cursor_overlay.show(x, y, "#FF4444", "Click")
                return _result(await _async_click(x, y, btn), f"Clicked {btn} at ({x}, {y})", task_id)
            btn = args[0] if args else "left"
            pos = desktop_service.get_mouse_position()
            if pos.get("success"):
                cursor_overlay.start()
                cursor_overlay.show(pos["x"], pos["y"], "#FF4444", "Click")
            return _result(await _async_click(None, None, btn), f"Clicked {btn}", task_id)

        elif action == "double_click":
            if len(args) >= 2:
                x, y = int(args[0]), int(args[1])
                cursor_overlay.start()
                cursor_overlay.show(x, y, "#FF8844", "Double Click")
                return _result(desktop_service.double_click(x, y), f"Double-clicked at ({x}, {y})", task_id)
            pos = desktop_service.get_mouse_position()
            if pos.get("success"):
                cursor_overlay.start()
                cursor_overlay.show(pos["x"], pos["y"], "#FF8844", "Double Click")
            return _result(desktop_service.double_click(), "Double-clicked", task_id)

        elif action == "right_click":
            if len(args) >= 2:
                x, y = int(args[0]), int(args[1])
                cursor_overlay.start()
                cursor_overlay.show(x, y, "#FF8844", "Right Click")
                return _result(desktop_service.right_click(x, y), f"Right-clicked at ({x}, {y})", task_id)
            pos = desktop_service.get_mouse_position()
            if pos.get("success"):
                cursor_overlay.start()
                cursor_overlay.show(pos["x"], pos["y"], "#FF8844", "Right Click")
            return _result(desktop_service.right_click(), "Right-clicked", task_id)

        elif action == "scroll":
            clicks = int(args[0]) if args else -3
            return _result(desktop_service.scroll(clicks), f"Scrolled {clicks}", task_id)

        elif action == "drag":
            if len(args) >= 4:
                sx, sy, ex, ey = int(args[0]), int(args[1]), int(args[2]), int(args[3])
                dur = float(args[4]) if len(args) > 4 else 0.5
                cursor_overlay.start()
                cursor_overlay.show(sx, sy, "#FF00FF", "Drag Start")
                return _result(desktop_service.drag(sx, sy, ex, ey, dur),
                              f"Dragged from ({sx},{sy}) to ({ex},{ey})", task_id)
            return _result({"success": False, "error": "Need sx sy ex ey"}, "", task_id)

        # ---- Keyboard ----
        elif action == "type":
            text = args[0] if args else ""
            cursor_overlay.start()
            pos = desktop_service.get_mouse_position()
            cx = pos.get("x", 0)
            cy = pos.get("y", 0)
            cursor_overlay.show(cx, cy, "#00AAFF", "Typing...", duration=min(1.0, len(text) * 0.05 + 0.3))
            return _result(desktop_service.type_text(text), f"Typed '{text[:80]}'", task_id)

        elif action == "press":
            key = args[0] if args else "enter"
            return _result(desktop_service.press_key(key), f"Pressed '{key}'", task_id)

        elif action == "hotkey":
            if not args:
                return _result({"success": False, "error": "Need at least one key"}, "", task_id)
            keys = tuple(args)
            return _result(desktop_service.hotkey(*keys), f"Pressed {'+'.join(keys)}", task_id)

        # ---- Screen ----
        elif action == "screenshot":
            r = desktop_service.screenshot()
            if r.get("success"):
                return {
                    "completed": True, "exit_code": 0,
                    "stdout": "Screenshot captured. [data: image/png;base64," + r["screenshot_base64"][:50] + "...]",
                    "screenshot_base64": r["screenshot_base64"],
                    "stderr": "", "task_id": task_id,
                }
            return _result(r, "", task_id)

        elif action == "screen_size":
            return _result(desktop_service.get_screen_size(),
                          f"Screen: {desktop_service.get_screen_size().get('width', '?')}x{desktop_service.get_screen_size().get('height', '?')}",
                          task_id)

        elif action == "mouse_position":
            return _result(desktop_service.get_mouse_position(),
                          f"Mouse at ({desktop_service.get_mouse_position().get('x', '?')}, {desktop_service.get_mouse_position().get('y', '?')})",
                          task_id)

        elif action == "pixel_color":
            if len(args) >= 2:
                x, y = int(args[0]), int(args[1])
                return _result(desktop_service.get_pixel_color(x, y),
                              f"Color at ({x},{y}): {desktop_service.get_pixel_color(x, y).get('color', '?')}",
                              task_id)
            return _result({"success": False, "error": "Need x y"}, "", task_id)

        # ---- Windows ----
        elif action == "list_windows":
            r = desktop_service.list_windows()
            if r.get("success"):
                titles = [w["title"] for w in r.get("windows", [])]
                return _result(r, f"Open windows:\n" + "\n".join(f"  - {t}" for t in titles), task_id)
            return _result(r, "", task_id)

        elif action == "focus":
            title = args[0] if args else ""
            return _result(desktop_service.focus_window(title), f"Focused '{title}'", task_id)

        elif action == "active_window":
            return _result(desktop_service.get_active_window(),
                          f"Active window: {desktop_service.get_active_window().get('title', '?')}",
                          task_id)

        elif action == "window_rect":
            title = args[0] if args else ""
            return _result(desktop_service.get_window_rect(title),
                          f"Window '{title}' rect: {desktop_service.get_window_rect(title)}",
                          task_id)

        elif action == "move_window":
            if len(args) >= 3:
                title, x, y = args[0], int(args[1]), int(args[2])
                return _result(desktop_service.move_window(title, x, y),
                              f"Moved '{title}' to ({x}, {y})", task_id)
            return _result({"success": False, "error": "Need title x y"}, "", task_id)

        elif action == "resize_window":
            if len(args) >= 3:
                title, w, h = args[0], int(args[1]), int(args[2])
                return _result(desktop_service.resize_window(title, w, h),
                              f"Resized '{title}' to {w}x{h}", task_id)
            return _result({"success": False, "error": "Need title width height"}, "", task_id)

        elif action == "minimize_window":
            title = args[0] if args else ""
            return _result(desktop_service.minimize_window(title), f"Minimized '{title}'", task_id)

        elif action == "maximize_window":
            title = args[0] if args else ""
            return _result(desktop_service.maximize_window(title), f"Maximized '{title}'", task_id)

        elif action == "restore_window":
            title = args[0] if args else ""
            return _result(desktop_service.restore_window(title), f"Restored '{title}'", task_id)

        elif action == "close_window":
            title = args[0] if args else ""
            return _result(desktop_service.close_window(title), f"Closed '{title}'", task_id)

        # ---- Clipboard ----
        elif action == "read_clipboard":
            r = desktop_service.read_clipboard()
            return _result(r, f"Clipboard: {r.get('text', '')[:200]}", task_id)

        elif action == "write_clipboard":
            text = args[0] if args else ""
            return _result(desktop_service.write_clipboard(text), f"Written {len(text)} chars to clipboard", task_id)

        # ---- App Launching & System UI ----
        elif action == "launch_app":
            app = " ".join(args) if args else ""
            if not app:
                return _result({"success": False, "error": "Need app name"}, "", task_id)
            cursor_overlay.start()
            ss = desktop_service.get_screen_size()
            if ss.get("success"):
                cursor_overlay.show(ss["width"] // 2, ss["height"] - 30, "#00AAFF", f"Launching {app}", duration=2.0)
            return _result(desktop_service.launch_app(app), f"Launched '{app}'", task_id)

        elif action == "open_settings":
            page = " ".join(args) if args else ""
            cursor_overlay.start()
            ss = desktop_service.get_screen_size()
            if ss.get("success"):
                cursor_overlay.show(ss["width"] // 2, ss["height"] - 30, "#00AAFF", f"Opening Settings", duration=2.0)
            return _result(desktop_service.open_settings(page), f"Opened Settings: {page or 'main'}", task_id)

        elif action == "open_url":
            url = " ".join(args) if args else ""
            if not url:
                return _result({"success": False, "error": "Need URL"}, "", task_id)
            return _result(desktop_service.open_url(url), f"Opened URL: {url}", task_id)

        elif action == "open_folder":
            path = " ".join(args) if args else ""
            if not path:
                return _result({"success": False, "error": "Need folder path or name"}, "", task_id)
            r = desktop_service.open_folder(path)
            if r.get("success"):
                return _result(r, f"Opened folder: {r['folder']}", task_id)
            return _result(r, f"Failed to open: {path}", task_id)

        elif action == "find_text":
            text = " ".join(args) if args else ""
            if not text:
                return _result({"success": False, "error": "Need text to find"}, "", task_id)
            r = desktop_service.find_text_on_screen(text)
            if r.get("success"):
                return _result(r, f"Found '{text}' in {r['count']} window(s)", task_id)
            return _result(r, f"Text '{text}' not found on screen", task_id)

        # ---- Unknown ----
        else:
            return {"completed": False, "exit_code": 1, "stdout": "",
                    "stderr": f"Unknown desktop action: {action}", "task_id": task_id}

    except Exception as e:
        log.error("desktop_command_failed", action=action, error=str(e))
        return {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(e), "task_id": task_id}


def _result(svc_result: dict, stdout: str, task_id: str) -> dict:
    """Wrap a DesktopService result dict into the standard command result format."""
    ok = svc_result.get("success", False)
    err = svc_result.get("error", "")
    return {
        "completed": ok,
        "exit_code": 0 if ok else 1,
        "stdout": stdout if ok else "",
        "stderr": "" if ok else (err or "Desktop action failed"),
        "task_id": task_id,
    }


async def _async_click(x, y, button):
    """Run click in executor since pyautogui.click can block."""
    import functools
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(desktop_service.click, x, y, button))


@router.post("")
async def process_chat(request: ChatRequest):
    """Processes natural language messages from Sir and returns responses with TTS audio."""
    log.info("chat_request_received", message_len=len(request.message), device_id=request.device_id)

    # Identify the source device
    source_device_id = request.device_id or ""
    source_device_type = "unknown"
    source_device_name = ""
    if source_device_id:
        src_ws = ws_manager.get_device(source_device_id)
        if src_ws:
            source_device_type = src_ws.device_type
            source_device_name = src_ws.device_name
    log.info("source_device", device_id=source_device_id, device_type=source_device_type)

    try:
        # =================================================================
        # PHASE 1: Server-side command detection (bypasses LLM completely)
        # =================================================================
        detected_commands = command_interpreter.interpret(request.message)
        command_results = []

        if detected_commands:
            log.info("commands_detected_by_interpreter", count=len(detected_commands))
            for description, cmd in detected_commands:
                log.info("dispatching_command", description=description, command=cmd)

                # Handle browser interaction commands (click/type/press on current page)
                if cmd.startswith("browser_click|"):
                    selector = cmd.split("|", 1)[1]
                    log.info("browser_click_on_page", selector=selector)
                    try:
                        bresult = await browser_service.click(selector)
                        ok = bresult.get("success", False)
                        err = bresult.get("error", "")
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Clicked '{selector}'" if ok else "",
                            "stderr": "" if ok else (err or "Playwright is not installed — cannot click. Sir, please perform this action manually in your browser."),
                            "task_id": "browser-click",
                        }
                    except Exception as be:
                        log.warning("browser_click_failed", error=str(be))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Browser interaction error: {be}. Sir, your input is required in the browser.", "task_id": "browser-click"}
                elif cmd.startswith("browser_type|"):
                    text = cmd.split("|", 1)[1]
                    log.info("browser_type_on_page", text=text[:30])
                    try:
                        bresult = await browser_service.type_text(":focus", text)
                        ok = bresult.get("success", False)
                        err = bresult.get("error", "")
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Typed '{text[:50]}' on page" if ok else "",
                            "stderr": "" if ok else (err or "Playwright is not installed — cannot type. Sir, please type this manually in your browser."),
                            "task_id": "browser-type",
                        }
                    except Exception as be:
                        log.warning("browser_type_failed", error=str(be))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Browser interaction error: {be}. Sir, your input is required in the browser.", "task_id": "browser-type"}
                elif cmd.startswith("browser_press|"):
                    key = cmd.split("|", 1)[1]
                    log.info("browser_press_key", key=key)
                    try:
                        bresult = await browser_service.press_key(key)
                        ok = bresult.get("success", False)
                        err = bresult.get("error", "")
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Pressed '{key}'" if ok else "",
                            "stderr": "" if ok else (err or "Playwright is not installed — cannot press keys. Sir, please press this key manually."),
                            "task_id": "browser-press",
                        }
                    except Exception as be:
                        log.warning("browser_press_failed", error=str(be))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Browser interaction error: {be}. Sir, your input is required.", "task_id": "browser-press"}
                elif cmd.startswith("browser_scroll|"):
                    direction = cmd.split("|", 1)[1]
                    log.info("browser_scroll", direction=direction)
                    try:
                        js = "window.scrollBy(0, 500)" if direction == "down" else "window.scrollBy(0, -500)"
                        bresult = await browser_service.execute_js(js)
                        ok = bresult.get("success", False)
                        err = bresult.get("error", "")
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Scrolled {direction}" if ok else "",
                            "stderr": "" if ok else (err or "Playwright not available — cannot scroll."),
                            "task_id": "browser-scroll",
                        }
                    except Exception as be:
                        log.warning("browser_scroll_failed", error=str(be))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(be), "task_id": "browser-scroll"}
                elif cmd.startswith("android_whatsapp_send|"):
                    # Structural command: android_whatsapp_send|contact|text
                    parts = cmd.split("|", 2)
                    if len(parts) != 3:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Invalid android_whatsapp_send payload", "task_id": "droid-whatsapp"}
                    else:
                        _, contact, text = parts
                        result = await _dispatch_droid_command_and_wait(
                            user_id=None,
                            target_device_type=DeviceType.MOBILE,
                            cmd="android_whatsapp_send",
                            payload={"contact": contact, "text": text},
                            timeout_seconds=30.0,
                        )
                elif cmd.startswith("android_sms_send|"):
                    # Structural command: android_sms_send|number|text
                    parts = cmd.split("|", 2)
                    if len(parts) != 3:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Invalid android_sms_send payload", "task_id": "droid-sms"}
                    else:
                        _, number, text = parts
                        result = await _dispatch_droid_command_and_wait(
                            user_id=None,
                            target_device_type=DeviceType.MOBILE,
                            cmd="android_sms_send",
                            payload={"number": number, "text": text},
                            timeout_seconds=30.0,
                        )
                elif cmd.startswith("instagram_dm_send|"):
                    parts = cmd.split("|", 2)
                    ig_user = parts[1].strip() if len(parts) > 1 else ""
                    ig_msg = parts[2].strip() if len(parts) > 2 else ""
                    if not ig_msg:
                        ig_msg = "مرحباً! كيف حالك؟ 😊"
                    try:
                        from backend.services.instagram_service import instagram_service
                        if not ig_user:
                            # No user specified — resolve to first inbox conversation
                            inbox_data = instagram_service.read_inbox(limit=5)
                            if inbox_data.get("success"):
                                convos = inbox_data.get("conversations", [])
                                if convos:
                                    uid = (convos[0].get("user_ids") or [None])[0]
                                    uname = (convos[0].get("users") or [None])[0]
                                    ig_user = uid or uname or ""
                                else:
                                    result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Instagram inbox is empty.", "task_id": "instagram-dm"}
                                    command_results.append({"description": description, "command": cmd, **result})
                                    continue
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": inbox_data.get("error", "Could not read inbox"), "task_id": "instagram-dm"}
                                command_results.append({"description": description, "command": cmd, **result})
                                continue
                        ig_result = instagram_service.send_dm(ig_user, ig_msg)
                        ok = ig_result.get("success", False)
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Instagram DM sent: {ig_msg[:60]}" if ok else "",
                            "stderr": "" if ok else ig_result.get("error", "Failed to send Instagram DM"),
                            "task_id": "instagram-dm",
                        }
                    except Exception as ig_err:
                        log.warning("instagram_dm_phase1_failed", error=str(ig_err))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Instagram DM failed: {ig_err}", "task_id": "instagram-dm"}
                elif cmd == "instagram_read_inbox":
                    try:
                        from backend.services.instagram_service import instagram_service
                        inbox_result = instagram_service.read_inbox(limit=10)
                        ok = inbox_result.get("success", False)
                        convos = inbox_result.get("conversations", [])
                        names = []
                        for c in convos:
                            name = (c.get("users") or [None])[0] or c.get("title") or "Unknown"
                            names.append(f"{name} ({c.get('thread_id', '?')[:8]}...)")
                        stdout = f"Instagram inbox conversations: {', '.join(names)}" if names else "Instagram inbox is empty or could not be read."
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": stdout if ok else "",
                            "stderr": "" if ok else inbox_result.get("error", "Failed to read Instagram inbox"),
                            "task_id": "instagram-inbox",
                        }
                    except Exception as ig_err:
                        log.warning("instagram_inbox_phase1_failed", error=str(ig_err))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Read inbox failed: {ig_err}", "task_id": "instagram-inbox"}
                elif cmd.startswith("desktop_os_execute|"):
                    # Structural command: desktop_os_execute|command
                    command = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not command:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Invalid desktop_os_execute payload", "task_id": "droid-desktop"}
                    else:
                        result = await _dispatch_droid_command_and_wait(
                            user_id=None,
                            target_device_type=DeviceType.DESKTOP,
                            cmd="desktop_os_execute",
                            payload={"command": command},
                            timeout_seconds=30.0,
                        )
                elif cmd.startswith("desktop_"):
                    log.info("desktop_command", command=cmd)
                    result = await _handle_desktop_command(cmd, prefix="desktop")
                elif any(kw in cmd.lower() for kw in BROWSER_ELIGIBLE):
                    # Route ALL browser-eligible URLs through the persistent Playwright
                    # browser so subsequent click/type/press commands work on the same page.
                    url_match = re.search(r'start "" "(.+?)"', cmd)
                    url = url_match.group(1) if url_match else cmd
                    log.info("routing_to_persistent_browser", url=url)
                    interact_ok = False
                    fallback_reason = ""
                    try:
                        iresult = await browser_service.interact(
                            url, [{"type": "wait", "value": "2000"}],
                        )
                        interact_ok = iresult.get("success", False)
                        if not interact_ok:
                            fallback_reason = iresult.get("error", "Unknown error")
                    except Exception as be:
                        log.warning("persistent_browser_failed_fallback", error=str(be))
                        fallback_reason = str(be)
                    if interact_ok:
                        page_info = ""
                        try:
                            pi = await browser_service.get_page_info()
                            if pi.get("success"):
                                page_url = pi.get("url", url)
                                page_title = pi.get("title", "")
                                is_login = pi.get("is_login_page", False)
                                page_info = f" Page title: '{page_title}'. Current URL: {page_url}."
                                if is_login:
                                    page_info += " LOGIN PAGE DETECTED — Sir is not logged in. Sir must log in before I can proceed with any page-specific actions."
                        except Exception:
                            pass
                        result = {
                            "completed": True, "exit_code": 0,
                            "stdout": f"Playwright browser opened to {url}. I have full control — I can click, type, and navigate on this page.{page_info}", "stderr": "", "task_id": "browser-interact",
                        }
                    else:
                        # Fallback: open via system default browser
                        log.info("interactive_fallback_to_shell", url=url, reason=fallback_reason)
                        shell_result = await _dispatch_and_wait(cmd, description, timeout=5.0)
                        # Mark as "completed with caveat" — page is open but we cannot interact
                        result = {
                            "completed": True, "exit_code": 0,
                            "stdout": f"Page '{url}' opened in your default browser. BROWSER AUTOMATION NOT AVAILABLE: {fallback_reason}. I cannot click, type, or navigate on this page. If Sir wants me to interact with it, install Playwright (pip install playwright && python -m playwright install chromium) or interact manually.",
                            "stderr": "browser_automation_unavailable",
                            "task_id": "browser-fallback-shell",
                        }
                else:
                    result = await _dispatch_and_wait(cmd, description, timeout=10.0)

                command_results.append({
                    "description": description,
                    "command": cmd,
                    **result,
                })

                # Broadcast progress to all connected devices (phone + PC)
                try:
                    await ws_manager.broadcast({
                        "type": "task_update",
                        "payload": {
                            "status": "progress",
                            "task_id": result.get("task_id", ""),
                            "description": description,
                            "completed": result.get("completed", False),
                            "command": cmd,
                            "source_device_id": source_device_id,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    })
                except Exception:
                    pass

        # =================================================================
        # PHASE 2: LLM reasoning (for conversation + fallback commands)
        # =================================================================
        history = [{"role": item["role"], "content": item["content"]} for item in dialogue_history[-10:]]

        # Build device-aware context for the LLM
        device_context = f"\n\n[SOURCE DEVICE] You are talking to Sir through device '{source_device_name}' ({source_device_type}, id={source_device_id}). "
        device_context += "When Sir says 'on my PC' or 'on the computer', route commands to a desktop/laptop device. "
        device_context += "When Sir says 'on my phone' or 'on mobile', route commands to a mobile device. "
        device_context += "When no target device is specified, execute commands on the device Sir is currently using.\n"

        # If commands were detected, tell the LLM about the results so it can
        # craft a natural response incorporating the execution output
        augmented_message = request.message
        if command_results:
            result_context = device_context + "\n[SYSTEM CONTEXT — Commands executed]\n"
            needs_input = False
            for cr in command_results:
                result_context += f"• {cr['description']}: "
                if cr["completed"]:
                    if cr["exit_code"] == 0:
                        output = cr["stdout"] or "Completed successfully with no output."
                        result_context += f"SUCCESS — {output}\n"
                    else:
                        error = cr["stderr"] or cr["stdout"] or "Unknown error"
                        result_context += f"FAILED (exit {cr['exit_code']}) — {error}\n"
                        if "browser_automation_unavailable" in (cr.get("stderr") or ""):
                            needs_input = True
                else:
                    result_context += "Still running in background...\n"
                # Check for patterns that indicate Sir's manual input is required
                stderr = cr.get("stderr") or ""
                if any(kw in stderr.lower() for kw in ["sir, your input is required", "please", "manually"]):
                    needs_input = True
            if needs_input:
                result_context += "\n[IMPORTANT] Sir's manual input or attention is required for one or more of the above commands. Inform Sir clearly and concisely about what needs to be done. Do NOT say 'I encountered an error' — say 'Sir, your input is required' and describe what action Sir needs to take.\n"
            else:
                result_context += "\nRespond naturally about these results in your JARVIS persona. Do NOT say you cannot control the device — the commands have already been executed.\nDo NOT generate <run_os_command> tags for commands that already executed.\n"
            augmented_message = request.message + result_context

        reply = await llm_service.get_response(
            user_message=augmented_message,
            chat_history=history,
            inject_memory=request.include_memory,
        )

        # =================================================================
        # PHASE 3: Parse <run_os_command> tags AND markdown code blocks from LLM (fallback)
        # =================================================================
        llm_commands = re.findall(r"<run_os_command>(.*?)</run_os_command>", reply, re.DOTALL)
        # Filter out non-executable status messages wrapped in tags by the LLM
        _status_patterns = re.compile(
            r"^(command\s+(completed|executed|ran|failed|not|is|was)|"
            r"(the\s+)?(error|failed|success|output|result).*|"
            r"'.*?'.*is not recognized|"
            r"exit\s+\d+|"
            r"(output|result|status):|"
            r"(opened|launched|started|closed)\s+(folder|file|app|application|program).*)",
            re.IGNORECASE,
        )
        def _is_valid_command(cmd: str) -> bool:
            s = cmd.strip()
            if not s or len(s) < 5:
                return False
            if _status_patterns.match(s):
                return False
            # Reject English-language phrases that are not real commands
            english_phrases = [
                "opening ", "launching ", "starting ", "closing ",
                "opened ", "launched ", "started ", "closed ",
                "searching for ", "looking for ", "finding ",
                "searched ", "found ", "created ", "deleted ",
                "here is ", "this is ", "i am ", "now ",
                "the file ", "the command ", "the result ",
                "sir,", "sir ", "yes, ", "certainly",
            ]
            lower_s = s.lower()
            if any(lower_s.startswith(p) for p in english_phrases) and not any(kw in lower_s for kw in ["desktop_", "browser_", "powershell"]):
                return False
            # Must contain at least one shell-like structure
            has_shell_marker = any(kw in lower_s for kw in [
                "powershell", ".exe", ".bat", ".ps1", ".cmd",
                "start ", "desktop_", "browser_",
                "generate_image", "generate_video", "create_excel",
                "download_file", "search_web", "fetch_url", "search_maps",
                "agent_", "instagram_dm_send", "instagram_read_inbox",
                "goal_execute",
                " | ", " >", ">>", " && ", " || ",
                " $", "@(",
            ])
            if not has_shell_marker and s.count(" ") <= 3:
                return False
            return True
        llm_commands = [c for c in llm_commands if _is_valid_command(c)]
        clean_reply = re.sub(r"<run_os_command>.*?</run_os_command>", "", reply, flags=re.DOTALL).strip()

        # Also extract markdown code blocks (backtick style) as commands
        if not llm_commands:
            md_blocks = re.findall(
                r"```(?:powershell|bash|cmd|shell|ps1|bat)?\s*\n?(.*?)\n?```",
                clean_reply, re.DOTALL,
            )
            for block in md_blocks:
                block = block.strip()
                if block and not block.startswith("#") and not block.startswith("//"):
                    llm_commands.append(block)
            if md_blocks:
                clean_reply = re.sub(r"```.*?```", "", clean_reply, flags=re.DOTALL).strip()

        # PHASE 3.5: If LLM mentioned creating a file but didn't execute, auto-generate command
        if not llm_commands:
            file_match = re.search(
                r"(?:created|made|wrote|saved|generated)\s+(?:a\s+)?(?:file\s+)?(?:called\s+|named\s+)?[\"']?(\S+?\.[a-z0-9]+)[\"']?",
                clean_reply, re.IGNORECASE,
            )
            if file_match:
                filename = file_match.group(1).strip().strip("'\".,")
                # Only auto-create if the interpreter didn't already handle it
                already_created = any(
                    filename.lower() in cr.get("command", "").lower()
                    for cr in command_results
                )
                if not already_created and not re.search(r"suggested|placeholder|example", filename, re.IGNORECASE):
                    safe_name = filename.replace("'", "''")
                    auto_cmd = f'powershell -Command "Set-Content -Path $env:USERPROFILE\\Desktop\\{safe_name} -Value \'Content created by JARVIS at your request, Sir.\'"'
                    llm_commands.append(auto_cmd)
                    log.info("auto_generated_file_command", filename=filename)

        # Convert PowerShell UI commands to desktop_ commands (human-like control)
        converted = []
        for raw in llm_commands:
            c = raw.strip()
            lower = c.lower()
            # explorer.exe / select, → desktop_open_folder|path
            if "explorer" in lower and ("/select" in lower or "desktop" in lower or "b2b" in lower):
                path_match = re.search(r'select,\s*(.+?)(?:\s*\)|\s*$)', c)
                if path_match:
                    converted.append(f"desktop_open_folder|{path_match.group(1).strip()}")
                else:
                    converted.append("desktop_open_folder|desktop")
                log.info("converted_explorer_to_desktop", original=c[:80], target="desktop_open_folder")
            # Start-Process ms-settings: → desktop_open_settings
            elif "start-process" in lower and "ms-settings" in lower:
                page_match = re.search(r"ms-settings:([\w-]+)", c)
                page = page_match.group(1) if page_match else ""
                converted.append(f"desktop_open_settings|{page}" if page else "desktop_open_settings")
                log.info("converted_powershell_to_desktop", original=c[:80], target="desktop_open_settings")
            # Start-Process for known apps → desktop_launch_app (but NOT for file-operations)
            elif "start-process" in lower and not any(kw in lower for kw in ["set-content", "out-file", "new-item", "explorer"]):
                name_match = re.search(r'(?:start-process)\s+(?:["\']?)(\w+)', c, re.IGNORECASE)
                if name_match:
                    app = name_match.group(1).strip("'\"")
                    converted.append(f"desktop_launch_app|{app}")
                    log.info("converted_start_process_to_desktop", original=c[:80], target=f"desktop_launch_app|{app}")
                else:
                    converted.append(c)
            else:
                converted.append(c)
        llm_commands = converted

        # Execute any LLM-generated commands that weren't already handled
        llm_command_results = []
        if llm_commands:
            log.info("llm_command_tags_detected", count=len(llm_commands))
            for cmd_raw in llm_commands:
                cmd = cmd_raw.strip()
                if not cmd:
                    continue
                # Don't re-execute if interpreter already handled a similar command (only if it succeeded)
                normalized = cmd.lower().strip().replace(".exe", "")
                already_handled = any(
                    (cr["command"].lower().strip().replace(".exe", "") == normalized
                     or normalized in cr["command"].lower()
                     or cr["command"].lower() in normalized)
                    and cr.get("completed", False)
                    for cr in command_results
                )
                # Special: if any instagram_dm_send was already handled, skip ALL instagram_dm_send variants
                if not already_handled and cmd.startswith("instagram_dm_send"):
                    already_handled = any(
                        cr["command"].startswith("instagram_dm_send") and cr.get("completed", False)
                        for cr in command_results
                    )
                if already_handled:
                    continue

                # Handle browser commands from LLM tags (same as Phase 1)
                if cmd.startswith("browser_click|"):
                    selector = cmd.split("|", 1)[1]
                    try:
                        bresult = await browser_service.click(selector)
                        result = {
                            "completed": bresult.get("success", False),
                            "exit_code": 0 if bresult.get("success") else 1,
                            "stdout": f"Clicked '{selector}'" if bresult.get("success") else bresult.get("error", "Failed"),
                            "stderr": "" if bresult.get("success") else bresult.get("error", ""),
                            "task_id": "llm-browser-click",
                        }
                    except Exception as be:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(be), "task_id": "llm-browser-click"}
                elif cmd.startswith("browser_type|"):
                    text = cmd.split("|", 1)[1]
                    try:
                        bresult = await browser_service.type_text(":focus", text)
                        result = {
                            "completed": bresult.get("success", False),
                            "exit_code": 0 if bresult.get("success") else 1,
                            "stdout": f"Typed '{text[:50]}' on page" if bresult.get("success") else bresult.get("error", "Failed"),
                            "stderr": "" if bresult.get("success") else bresult.get("error", ""),
                            "task_id": "llm-browser-type",
                        }
                    except Exception as be:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(be), "task_id": "llm-browser-type"}
                elif cmd.startswith("browser_press|"):
                    key = cmd.split("|", 1)[1]
                    try:
                        bresult = await browser_service.press_key(key)
                        result = {
                            "completed": bresult.get("success", False),
                            "exit_code": 0 if bresult.get("success") else 1,
                            "stdout": f"Pressed '{key}'" if bresult.get("success") else bresult.get("error", "Failed"),
                            "stderr": "" if bresult.get("success") else bresult.get("error", ""),
                            "task_id": "llm-browser-press",
                        }
                    except Exception as be:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(be), "task_id": "llm-browser-press"}
                elif cmd.startswith("browser_scroll|"):
                    direction = cmd.split("|", 1)[1]
                    try:
                        js = "window.scrollBy(0, 500)" if direction == "down" else "window.scrollBy(0, -500)"
                        bresult = await browser_service.execute_js(js)
                        result = {
                            "completed": bresult.get("success", False),
                            "exit_code": 0 if bresult.get("success") else 1,
                            "stdout": f"Scrolled {direction}" if bresult.get("success") else bresult.get("error", "Failed"),
                            "stderr": "" if bresult.get("success") else bresult.get("error", ""),
                            "task_id": "llm-browser-scroll",
                        }
                    except Exception as be:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(be), "task_id": "llm-browser-scroll"}
                elif cmd.startswith("generate_image|"):
                    parts = cmd.split("|")
                    prompt = parts[1] if len(parts) > 1 else ""
                    model = parts[2] if len(parts) > 2 else None
                    size = parts[3] if len(parts) > 3 else None
                    if not prompt:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No prompt provided for image generation", "task_id": "llm-gen-img"}
                    else:
                        log.info("generating_image_from_llm", prompt=prompt[:60], model=model)
                        try:
                            gen_result = await svc_generate_image(prompt.strip(), model=(model or None), size=(size or None))
                            if gen_result.get("success"):
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Image generated successfully.\n![Generated Image]({gen_result['url']})",
                                    "image_url": gen_result.get("url", ""),
                                    "stderr": "", "task_id": "llm-gen-img",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": gen_result.get("error", "Image generation failed"), "task_id": "llm-gen-img"}
                        except Exception as ge:
                            log.error("llm_image_generation_failed", error=str(ge))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ge), "task_id": "llm-gen-img"}
                elif cmd.startswith("generate_video|"):
                    parts = cmd.split("|")
                    prompt = parts[1] if len(parts) > 1 else ""
                    model = parts[2] if len(parts) > 2 else None
                    duration = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
                    if not prompt:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No prompt provided for video generation", "task_id": "llm-gen-vid"}
                    else:
                        log.info("generating_video_from_llm", prompt=prompt[:60], model=model, duration=duration)
                        try:
                            gen_result = await svc_generate_video(prompt.strip(), model=(model or None), duration=duration)
                            if gen_result.get("success"):
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Video generated successfully.\n[Generated Video]({gen_result['url']})",
                                    "video_url": gen_result.get("url", ""),
                                    "stderr": "", "task_id": "llm-gen-vid",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": gen_result.get("error", "Video generation failed"), "task_id": "llm-gen-vid"}
                        except Exception as ge:
                            log.error("llm_video_generation_failed", error=str(ge))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ge), "task_id": "llm-gen-vid"}
                elif cmd.startswith("download_file|"):
                    url = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not url:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No URL provided for download", "task_id": "llm-dl"}
                    else:
                        log.info("downloading_file_from_llm", url=url[:100])
                        try:
                            dr = await file_download_service.download(url.strip())
                            if dr.get("success"):
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"File downloaded: {dr['filepath']} ({dr['size_bytes'] // 1024}KB)",
                                    "stderr": "", "task_id": "llm-dl",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": dr.get("error", "Download failed"), "task_id": "llm-dl"}
                        except Exception as de:
                            log.error("llm_download_failed", error=str(de))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(de), "task_id": "llm-dl"}
                elif cmd.startswith("search_web|"):
                    query = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not query:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No search query provided", "task_id": "llm-search"}
                    else:
                        log.info("web_search_from_llm", query=query[:60])
                        try:
                            sr = await web_search_service.search_web(query.strip())
                            if sr.get("success"):
                                output_lines = []
                                for i, r in enumerate(sr.get("results", [])[:5], 1):
                                    output_lines.append(f"{i}. {r['title']}\n   {r['snippet'][:150]}\n   {r['url']}")
                                output = "\n\n".join(output_lines) if output_lines else "No results found."
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Search results for '{query}':\n\n{output}",
                                    "stderr": "", "task_id": "llm-search",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": sr.get("error", "Search failed"), "task_id": "llm-search"}
                        except Exception as se:
                            log.error("llm_search_failed", error=str(se))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(se), "task_id": "llm-search"}
                elif cmd.startswith("fetch_url|"):
                    url = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not url:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No URL provided", "task_id": "llm-fetch"}
                    else:
                        log.info("fetch_url_from_llm", url=url)
                        try:
                            fr = await web_search_service.fetch_url(url.strip())
                            if fr.get("success"):
                                content = fr.get("content", "")[:3000]
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Content from {url}:\n\n{content}",
                                    "stderr": "", "task_id": "llm-fetch",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": fr.get("error", "Fetch failed"), "task_id": "llm-fetch"}
                        except Exception as fe:
                            log.error("llm_fetch_failed", error=str(fe))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(fe), "task_id": "llm-fetch"}
                elif cmd.startswith("search_maps|"):
                    parts = cmd.split("|")
                    query = parts[1] if len(parts) > 1 else ""
                    location = parts[2] if len(parts) > 2 else ""
                    if not query:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No search query provided", "task_id": "llm-maps"}
                    else:
                        log.info("maps_search_from_llm", query=query[:60], location=location[:40])
                        try:
                            mr = await web_search_service.search_maps(query.strip(), location.strip())
                            if mr.get("success"):
                                output_lines = []
                                for i, r in enumerate(mr.get("results", [])[:5], 1):
                                    output_lines.append(f"{i}. {r['title']}\n   {r['snippet'][:150]}\n   {r['url']}")
                                output = "\n\n".join(output_lines) if output_lines else "No places found."
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Places matching '{query}' in {location or 'any location'}:\n\n{output}",
                                    "stderr": "", "task_id": "llm-maps",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": mr.get("error", "Maps search failed"), "task_id": "llm-maps"}
                        except Exception as me:
                            log.error("llm_maps_failed", error=str(me))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(me), "task_id": "llm-maps"}
                elif cmd.startswith("create_excel|"):
                    parts = cmd.split("|")
                    filename = parts[1] if len(parts) > 1 else "output.xlsx"
                    sheet_name = parts[2] if len(parts) > 2 else "Sheet1"
                    if len(parts) < 4:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Missing headers/rows for Excel creation", "task_id": "llm-excel"}
                    else:
                        headers = [h.strip().strip("\"'") for h in parts[3].split(",")]
                        rows = []
                        for row_part in parts[4:]:
                            row = [v.strip().strip("\"'") for v in row_part.split(",")]
                            rows.append(row)
                        log.info("creating_excel", filename=filename, sheet=sheet_name, cols=len(headers), rows=len(rows))
                        try:
                            er = await excel_service.create_from_csv_data(
                                filename=filename,
                                sheet_name=sheet_name,
                                headers=headers,
                                rows=rows,
                            )
                            if er.get("success"):
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Excel file created: {er['filepath']} ({er['rows']} rows, {er['sheets']} sheet(s))",
                                    "stderr": "", "task_id": "llm-excel",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": er.get("error", "Excel creation failed"), "task_id": "llm-excel"}
                        except Exception as ee:
                            log.error("llm_excel_failed", error=str(ee))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ee), "task_id": "llm-excel"}
                elif cmd.startswith("instagram_dm_send|"):
                    # instagram_dm_send|username|message
                    parts = cmd.split("|", 2)
                    ig_user = parts[1].strip() if len(parts) > 1 else ""
                    ig_msg = parts[2].strip() if len(parts) > 2 else ""
                    if not ig_msg:
                        import random
                        greetings = [
                            "مرحباً! أنا جارفيس، المساعد الشخصي للسيد. أتمنى أن تكون بأفضل حال!",
                            "أهلاً! أنا جارفيس، مساعد السيد الآلي. كيف حالك؟ تسعدني أحوالك.",
                            "مرحباً! جارفيس هنا، مساعد السيد الشخصي. حابب أطمن عليك، كيف الأمور؟",
                            "السلام عليكم! أنا جارفيس، المساعد الذكي للسيد. أتمنى لك يوماً رائعاً!",
                            "أهلاً وسهلاً! أنا جارفيس، وأنا هنا نيابة عن السيد لأقول مرحباً وأطمن عليك.",
                        ]
                        ig_msg = random.choice(greetings)
                        log.info("instagram_dm_auto_message", chosen=ig_msg[:50])
                    log.info("instagram_dm_send", username=ig_user or "first conversation", message_len=len(ig_msg))
                    try:
                        from backend.services.instagram_service import instagram_service
                        send_as = ig_user
                        if not send_as:
                            # Resolve to first inbox contact
                            inbox_data = instagram_service.read_inbox(limit=5)
                            if inbox_data.get("success"):
                                convos = inbox_data.get("conversations", [])
                                if convos:
                                    uid = (convos[0].get("user_ids") or [None])[0]
                                    uname = (convos[0].get("users") or [None])[0]
                                    send_as = uid or uname or ""
                            if not send_as:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Instagram inbox is empty.", "task_id": "instagram-dm"}
                            else:
                                ig_result = instagram_service.send_dm(send_as, ig_msg)
                                if ig_result.get("success"):
                                    result = {"completed": True, "exit_code": 0, "stdout": f"Instagram DM sent to first contact: {ig_msg}", "stderr": "", "task_id": "instagram-dm"}
                                else:
                                    err = ig_result.get("error", "Instagram DM failed")
                                    result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": err, "task_id": "instagram-dm"}
                        else:
                            ig_result = instagram_service.send_dm(send_as, ig_msg)
                            if ig_result.get("success"):
                                result = {"completed": True, "exit_code": 0, "stdout": f"Instagram DM sent to '{ig_user}': {ig_msg}", "stderr": "", "task_id": "instagram-dm"}
                            else:
                                err = ig_result.get("error", "Instagram DM failed")
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": err, "task_id": "instagram-dm"}
                    except Exception as ige:
                        log.error("instagram_dm_send_failed", error=str(ige))
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ige), "task_id": "instagram-dm"}
                elif cmd == "instagram_read_inbox":
                    log.info("instagram_read_inbox")
                    try:
                        from backend.services.instagram_service import instagram_service
                        inbox_result = instagram_service.read_inbox(limit=10)
                        if inbox_result.get("success"):
                            convos = inbox_result.get("conversations", [])
                            convo_lines = []
                            for c in convos:
                                name = (c.get("users") or [None])[0] or c.get("title") or "Unknown"
                                convo_lines.append(f"- {name} ({c.get('thread_id', '?')[:8]}...)")
                            convo_list = "\n".join(convo_lines) if convo_lines else "No conversations found."
                            result = {
                                "completed": True, "exit_code": 0,
                                "stdout": f"Instagram inbox conversations:\n{convo_list}",
                                "stderr": "", "task_id": "instagram-inbox",
                            }
                        else:
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": inbox_result.get("error", "Could not read inbox"), "task_id": "instagram-inbox"}
                    except Exception as ire:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ire), "task_id": "instagram-inbox"}
                elif cmd.startswith("goal_execute|"):
                    goal = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not goal:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No goal provided", "task_id": "llm-goal"}
                    else:
                        log.info("goal_execute_from_llm", goal=goal[:80])
                        try:
                            from backend.services.goal_executor import goal_executor
                            gr = await goal_executor.execute_goal(goal=goal.strip(), max_iterations=20, timeout_seconds=600)
                            if gr.get("success"):
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Goal achieved: {gr.get('summary', 'Completed successfully.')}",
                                    "stderr": "", "task_id": "llm-goal",
                                }
                            else:
                                result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": gr.get("error", "Goal execution failed"), "task_id": "llm-goal"}
                        except Exception as ge:
                            log.error("llm_goal_failed", error=str(ge))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ge), "task_id": "llm-goal"}
                elif cmd.startswith("agent_") and "|" in cmd:
                    parts = cmd.split("|")
                    agent_type_str = parts[1] if len(parts) > 1 else ""
                    action = parts[2] if len(parts) > 2 else ""
                    payload_str = parts[3] if len(parts) > 3 else "{}"
                    if not agent_type_str:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "No agent type specified", "task_id": "llm-agent"}
                    else:
                        try:
                            agent_enum = AgentType(agent_type_str)
                            import json
                            try:
                                payload = json.loads(payload_str)
                            except json.JSONDecodeError:
                                payload = {"action": action, "raw": " ".join(parts[3:]) if len(parts) > 3 else {}}
                            if action:
                                payload["action"] = action
                            task_def = TaskDefinition(
                                title=f"Agent {agent_type_str}: {action}",
                                description=cmd[:200],
                                agent_type=agent_enum,
                                payload=payload,
                            )
                            log.info("routing_to_agent", agent=agent_type_str, action=action)
                            task_id = await task_manager.create_task(task_def)
                            # Run directly via orchestrator for synchronous response
                            tresult = await agent_orchestrator.execute_task(task_def)
                            if tresult.status == TaskStatus.COMPLETED:
                                output = str(tresult.result or {})[:2000]
                                result = {
                                    "completed": True, "exit_code": 0,
                                    "stdout": f"Agent '{agent_type_str}' completed: {output}",
                                    "stderr": "", "task_id": task_id,
                                }
                            else:
                                result = {
                                    "completed": False, "exit_code": 1,
                                    "stdout": "", "stderr": tresult.error or f"Agent '{agent_type_str}' failed",
                                    "task_id": task_id,
                                }
                        except ValueError:
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": f"Unknown agent type: {agent_type_str}", "task_id": "llm-agent"}
                        except Exception as ae:
                            log.error("llm_agent_failed", error=str(ae))
                            result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": str(ae), "task_id": "llm-agent"}
                elif cmd.startswith("desktop_os_execute|"):
                    command = cmd.split("|", 1)[1] if "|" in cmd else ""
                    if not command:
                        result = {"completed": False, "exit_code": 1, "stdout": "", "stderr": "Invalid desktop_os_execute payload", "task_id": "llm-desktop-exec"}
                    else:
                        # Try routed to specific desktop device first, fallback to local
                        routed = await _dispatch_droid_command_and_wait(
                            user_id=None,
                            target_device_type=DeviceType.DESKTOP,
                            cmd="desktop_os_execute",
                            payload={"command": command},
                            timeout_seconds=30.0,
                        )
                        if routed.get("completed"):
                            result = routed
                            result["task_id"] = "llm-desktop-routed"
                        else:
                            result = await _dispatch_and_wait(command, f"LLM desktop command: {command}", timeout=10.0)
                            result["task_id"] = "llm-desktop-local"
                elif cmd.startswith("desktop_"):
                    log.info("llm_desktop_command", command=cmd)
                    result = await _handle_desktop_command(cmd, prefix="llm-desktop")
                elif any(kw in cmd.lower() for kw in BROWSER_ELIGIBLE):
                    # Route LLM-generated browser commands through persistent browser too
                    url_match = re.search(r'start "" "(.+?)"', cmd)
                    url = url_match.group(1) if url_match else cmd
                    log.info("routing_llm_to_persistent_browser", url=url)
                    try:
                        iresult = await browser_service.navigate(url)
                        ok = iresult.get("success", False)
                        result = {
                            "completed": ok,
                            "exit_code": 0 if ok else 1,
                            "stdout": f"Navigated to {url}" if ok else iresult.get("error", "Failed"),
                            "stderr": "" if ok else iresult.get("error", ""),
                            "task_id": "llm-browser-navigate",
                        }
                    except Exception as be:
                        log.warning("llm_browser_navigate_failed", error=str(be))
                        result = await _dispatch_and_wait(cmd, f"LLM command: {cmd}", timeout=10.0)
                else:
                    # Show cursor overlay for PowerShell/OS commands too
                    try:
                        cursor_overlay.start()
                        pos = desktop_service.get_mouse_position()
                        if pos.get("success"):
                            cursor_overlay.show(pos["x"], pos["y"], "#00AAFF", "Executing...", duration=1.0)
                        else:
                            ss = desktop_service.get_screen_size()
                            if ss.get("success"):
                                cursor_overlay.show(ss["width"] // 2, ss["height"] - 60, "#00AAFF", "JARVIS Executing...", duration=1.5)
                    except Exception:
                        pass
                    result = await _dispatch_and_wait(cmd, f"LLM command: {cmd}", timeout=10.0)

                llm_command_results.append({
                    "description": f"Executed: {cmd}",
                    "command": cmd,
                    **result,
                })

                # Broadcast LLM command progress to all connected devices
                try:
                    await ws_manager.broadcast({
                        "type": "task_update",
                        "payload": {
                            "status": "progress",
                            "task_id": result.get("task_id", ""),
                            "description": f"LLM: {cmd[:80]}",
                            "completed": result.get("completed", False),
                            "command": cmd,
                            "source_device_id": source_device_id,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    })
                except Exception:
                    pass

        # =================================================================
        # PHASE 4: Build the final response
        # =================================================================
        all_results = command_results + llm_command_results

        # If interpreter handled commands but LLM gave no useful reply, generate one
        if not clean_reply and all_results:
            clean_reply = "Certainly, Sir. Executing your request now."

        # Append execution results to the response
        result_text = ""
        for cr in all_results:
            if cr["completed"]:
                if cr["exit_code"] == 0:
                    output = cr["stdout"] or "Command completed successfully."
                    result_text += f"\n\n**⚡ {cr['description']}**\n```\n{output}\n```"
                else:
                    error = cr["stderr"] or cr["stdout"] or "Unknown error"
                    result_text += f"\n\n**⚠️ {cr['description']} (Exit {cr['exit_code']})**\n```\n{error}\n```"
            else:
                result_text += f"\n\n*🔄 {cr['description']} — running in background, Sir. I'll report when complete.*"

        final_reply = clean_reply + result_text

        # Store dialogue in history (cap at 20 turns to prevent memory issues)
        dialogue_history.append({"role": "user", "content": request.message})
        dialogue_history.append({"role": "assistant", "content": final_reply})
        if len(dialogue_history) > 40:  # 20 turns
            dialogue_history[:20] = []

        # Store in memory database
        memory_id = ""
        if request.include_memory:
            try:
                memory_id = await memory_service.add_memory(
                    content=f"Sir said: '{request.message}'. JARVIS responded: '{final_reply}'",
                    category=MemoryCategory.CONVERSATIONS,
                    source="chat_session",
                    tags=["interaction", "chat_log"],
                )
            except Exception as mem_err:
                log.error("auto_memory_storage_failed", error=str(mem_err))

        # Record command executions for pattern detection
        try:
            from backend.services.pattern_detector import pattern_detector
            for cr in all_results:
                cmd = cr.get("command", cr.get("description", ""))
                if cmd:
                    pattern_detector.record_execution(
                        command=cmd,
                        success=cr.get("completed", False),
                        output=cr.get("stdout", ""),
                        user_intent=request.message,
                    )
        except Exception as pd_err:
            log.debug("pattern_recording_skipped", error=str(pd_err))

        # Generate TTS audio for the clean text (if not muted)
        tts_text = clean_reply
        audio_b64 = ""
        if request.tts_enabled and tts_service._available:
            try:
                audio_bytes = await tts_service.generate_speech(tts_text)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                log.info("tts_generated_for_chat", audio_size=len(audio_bytes))
            except Exception as tts_err:
                log.error("tts_generation_failed_in_chat", error=str(tts_err))
        else:
            log.info("tts_skipped_unavailable_or_muted")

        return {
            "content": final_reply,
            "conversation_id": request.conversation_id or "default_session",
            "agents_invoked": [AgentType.OS.value] if all_results else [],
            "command_results": all_results,
            "tasks_created": [cr["task_id"] for cr in all_results if "task_id" in cr],
            "memories_stored": [memory_id] if memory_id else [],
            "audio_base64": audio_b64,
        }

    except Exception as e:
        log.error("chat_processing_failed", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while generating reply: {str(e)}",
        )
