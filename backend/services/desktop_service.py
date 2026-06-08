"""
Full desktop control service for JARVIS OMEGA.
Provides mouse, keyboard, window, clipboard, and screen control
via PyAutoGUI, PyGetWindow, and pyperclip.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any, Dict, List, Optional, Tuple

import pyautogui
import pygetwindow as gw
import pyperclip
from PIL import Image

from shared.logger import get_logger

log = get_logger("desktop_service")

# Disable PyAutoGUI's fail-safe (moving mouse to top-left corner)
pyautogui.FAILSAFE = False
# Set pause between PyAutoGUI actions
pyautogui.PAUSE = 0.1


class DesktopService:
    """
    Full desktop control: mouse, keyboard, windows, clipboard, screenshot.
    All methods return a dict with at least 'success' and optionally 'error'/'data'.
    """

    # ====================================================================
    # Mouse Control
    # ====================================================================

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> Dict[str, Any]:
        """Move the mouse cursor to an absolute screen position."""
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"success": True}
        except Exception as e:
            log.error("mouse_move_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def click(self, x: Optional[int] = None, y: Optional[int] = None,
              button: str = "left") -> Dict[str, Any]:
        """Click mouse button at current or specified position."""
        try:
            if x is not None and y is not None:
                pyautogui.click(x, y, button=button)
            else:
                pyautogui.click(button=button)
            return {"success": True}
        except Exception as e:
            log.error("mouse_click_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def double_click(self, x: Optional[int] = None,
                     y: Optional[int] = None) -> Dict[str, Any]:
        """Double-click at current or specified position."""
        try:
            if x is not None and y is not None:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.doubleClick()
            return {"success": True}
        except Exception as e:
            log.error("double_click_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def right_click(self, x: Optional[int] = None,
                    y: Optional[int] = None) -> Dict[str, Any]:
        """Right-click at current or specified position."""
        try:
            if x is not None and y is not None:
                pyautogui.rightClick(x, y)
            else:
                pyautogui.rightClick()
            return {"success": True}
        except Exception as e:
            log.error("right_click_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def scroll(self, clicks: int,
               x: Optional[int] = None, y: Optional[int] = None) -> Dict[str, Any]:
        """Scroll the mouse wheel. Positive = up, Negative = down."""
        try:
            pyautogui.scroll(clicks, x=x, y=y)
            return {"success": True, "clicks": clicks}
        except Exception as e:
            log.error("scroll_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             duration: float = 0.5, button: str = "left") -> Dict[str, Any]:
        """Drag from (start_x, start_y) to (end_x, end_y)."""
        try:
            pyautogui.moveTo(start_x, start_y, duration=0.1)
            pyautogui.drag(end_x - start_x, end_y - start_y,
                          duration=duration, button=button)
            return {"success": True}
        except Exception as e:
            log.error("drag_failed", error=str(e))
            return {"success": False, "error": str(e)}

    # ====================================================================
    # Keyboard Control
    # ====================================================================

    def type_text(self, text: str, interval: float = 0.02) -> Dict[str, Any]:
        """Type a string of text at the current focus."""
        try:
            pyautogui.write(text, interval=interval)
            return {"success": True, "characters": len(text)}
        except Exception as e:
            log.error("typing_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def press_key(self, key: str) -> Dict[str, Any]:
        """Press and release a single keyboard key."""
        try:
            pyautogui.press(key)
            return {"success": True}
        except Exception as e:
            log.error("key_press_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def hotkey(self, *keys: str) -> Dict[str, Any]:
        """
        Press a combination of keys simultaneously.
        Example: hotkey('ctrl', 'c') for Copy.
        """
        try:
            pyautogui.hotkey(*keys)
            return {"success": True, "combination": "+".join(keys)}
        except Exception as e:
            log.error("hotkey_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def key_down(self, key: str) -> Dict[str, Any]:
        """Hold down a key."""
        try:
            pyautogui.keyDown(key)
            return {"success": True}
        except Exception as e:
            log.error("key_down_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def key_up(self, key: str) -> Dict[str, Any]:
        """Release a held key."""
        try:
            pyautogui.keyUp(key)
            return {"success": True}
        except Exception as e:
            log.error("key_up_failed", error=str(e))
            return {"success": False, "error": str(e)}

    # ====================================================================
    # Screen / Screenshot
    # ====================================================================

    def get_screen_size(self) -> Dict[str, Any]:
        """Get the display resolution."""
        try:
            w, h = pyautogui.size()
            return {"success": True, "width": w, "height": h}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None
                   ) -> Dict[str, Any]:
        """
        Take a screenshot of the whole screen or a region.
        Returns base64-encoded PNG.
        """
        try:
            img: Image.Image = pyautogui.screenshot(region=region)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return {
                "success": True,
                "screenshot_base64": b64,
                "width": img.width,
                "height": img.height,
            }
        except Exception as e:
            log.error("screenshot_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def locate_on_screen(self, image_path: str,
                         confidence: float = 0.8) -> Dict[str, Any]:
        """
        Find an image on the screen and return its position.
        image_path can be a file path or a PIL image.
        """
        try:
            pos = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if pos:
                return {
                    "success": True,
                    "left": pos.left, "top": pos.top,
                    "width": pos.width, "height": pos.height,
                    "center": (pos.left + pos.width // 2, pos.top + pos.height // 2),
                }
            return {"success": False, "error": "Image not found on screen"}
        except Exception as e:
            log.error("locate_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_pixel_color(self, x: int, y: int) -> Dict[str, Any]:
        """Get the RGB color of a pixel at the given coordinates."""
        try:
            color = pyautogui.pixel(x, y)
            return {"success": True, "color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                    "rgb": list(color)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ====================================================================
    # Window Management
    # ====================================================================

    def list_windows(self) -> Dict[str, Any]:
        """List all visible windows with their titles."""
        try:
            windows = gw.getAllWindows()
            visible = [
                {"title": w.title, "left": w.left, "top": w.top,
                 "width": w.width, "height": w.height, "is_active": w.isActive,
                 "is_minimized": w.isMinimized, "is_maximized": w.isMaximized}
                for w in windows if w.title.strip()
            ]
            return {"success": True, "windows": visible, "count": len(visible)}
        except Exception as e:
            log.error("list_windows_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def focus_window(self, title: str) -> Dict[str, Any]:
        """Bring a window to the foreground by matching its title."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            target = windows[0]
            if target.isMinimized:
                target.restore()
            target.activate()
            time.sleep(0.3)
            return {"success": True, "title": target.title}
        except Exception as e:
            log.error("focus_window_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_active_window(self) -> Dict[str, Any]:
        """Get info about the currently active window."""
        try:
            w = gw.getActiveWindow()
            if not w:
                return {"success": False, "error": "No active window found"}
            return {
                "success": True,
                "title": w.title,
                "left": w.left, "top": w.top,
                "width": w.width, "height": w.height,
                "is_maximized": w.isMaximized,
                "is_minimized": w.isMinimized,
            }
        except Exception as e:
            log.error("active_window_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_window_rect(self, title: str) -> Dict[str, Any]:
        """Get the position and size of a window by title."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            w = windows[0]
            return {
                "success": True,
                "title": w.title,
                "left": w.left, "top": w.top,
                "width": w.width, "height": w.height,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def move_window(self, title: str, x: int, y: int) -> Dict[str, Any]:
        """Move a window to an absolute screen position."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].moveTo(x, y)
            return {"success": True, "title": windows[0].title, "x": x, "y": y}
        except Exception as e:
            log.error("move_window_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def resize_window(self, title: str, width: int,
                      height: int) -> Dict[str, Any]:
        """Resize a window to specified dimensions."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].resizeTo(width, height)
            return {"success": True, "title": windows[0].title,
                    "width": width, "height": height}
        except Exception as e:
            log.error("resize_window_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def minimize_window(self, title: str) -> Dict[str, Any]:
        """Minimize a window."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].minimize()
            return {"success": True, "title": windows[0].title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def maximize_window(self, title: str) -> Dict[str, Any]:
        """Maximize a window."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].maximize()
            return {"success": True, "title": windows[0].title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restore_window(self, title: str) -> Dict[str, Any]:
        """Restore a minimized or maximized window."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].restore()
            return {"success": True, "title": windows[0].title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_window(self, title: str) -> Dict[str, Any]:
        """Close a window by title."""
        try:
            windows = gw.getWindowsWithTitle(title)
            if not windows:
                return {"success": False, "error": f"No window found matching '{title}'"}
            windows[0].close()
            return {"success": True, "title": windows[0].title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ====================================================================
    # Clipboard
    # ====================================================================

    def read_clipboard(self) -> Dict[str, Any]:
        """Read text from the system clipboard."""
        try:
            text = pyperclip.paste()
            return {"success": True, "text": text, "length": len(text)}
        except Exception as e:
            log.error("read_clipboard_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def write_clipboard(self, text: str) -> Dict[str, Any]:
        """Write text to the system clipboard."""
        try:
            pyperclip.copy(text)
            return {"success": True, "length": len(text)}
        except Exception as e:
            log.error("write_clipboard_failed", error=str(e))
            return {"success": False, "error": str(e)}

    # ====================================================================
    # Mouse Position / Info
    # ====================================================================

    def get_mouse_position(self) -> Dict[str, Any]:
        """Get the current mouse cursor position."""
        try:
            x, y = pyautogui.position()
            return {"success": True, "x": x, "y": y}
        except Exception as e:
            return {"success": False, "error": str(e)}


    # ====================================================================
    # App Launching & System UI
    # ====================================================================

    def launch_app(self, app_name: str) -> Dict[str, Any]:
        """Launch an application by name. Uses shell: URI or direct path."""
        import subprocess
        try:
            app_map = {
                "settings": "ms-settings:",
                "calculator": "calc:",
                "store": "ms-windows-store:",
                "camera": "ms-camera:",
                "calendar": "outlookcal:",
                "mail": "outlookmail:",
                "maps": "bingmaps:",
                "news": "ms-news:",
                "photos": "ms-photos:",
                "snipping tool": "ms-screensketch:",
                "sound": "ms-sound:",
                "alarms": "ms-clock:",
                "notepad": "notepad",
                "paint": "mspaint",
                "cmd": "cmd",
                "command prompt": "cmd",
                "powershell": "powershell",
                "task manager": "taskmgr",
                "control panel": "control",
                "file explorer": "explorer",
                "edge": "msedge",
                "chrome": "chrome",
                "firefox": "firefox",
                "vs code": "code",
                "visual studio code": "code",
            }
            key = app_name.lower().strip()
            target = app_map.get(key, app_name)
            subprocess.Popen(f'start "" "{target}"', shell=True)
            return {"success": True, "app": app_name, "launched_with": target}
        except Exception as e:
            log.error("launch_app_failed", app=app_name, error=str(e))
            return {"success": False, "error": str(e)}

    def open_settings(self, page: str = "") -> Dict[str, Any]:
        """Open Windows Settings, optionally to a specific page."""
        import subprocess
        try:
            page_map = {
                "bluetooth": "ms-settings:bluetooth",
                "network": "ms-settings:network",
                "wifi": "ms-settings:network-wifi",
                "display": "ms-settings:display",
                "sound": "ms-settings:sound",
                "notifications": "ms-settings:notifications",
                "apps": "ms-settings:appsfeatures",
                "default apps": "ms-settings:defaultapps",
                "battery": "ms-settings:batterysaver",
                "storage": "ms-settings:storagesense",
                "privacy": "ms-settings:privacy",
                "microphone": "ms-settings:privacy-microphone",
                "camera": "ms-settings:privacy-webcam",
                "location": "ms-settings:privacy-location",
                "background apps": "ms-settings:privacy-backgroundapps",
                "taskbar": "ms-settings:taskbar",
                "search": "ms-settings:search",
                "gaming": "ms-settings:gaming-gamebar",
                "startup": "ms-settings:startupapps",
                "accounts": "ms-settings:accounts",
                "sign in": "ms-settings:signinoptions",
                "dynamic lock": "ms-settings:signinoptions-dynamiclock",
                "lock screen": "ms-settings:lockscreen",
                "themes": "ms-settings:themes",
                "fonts": "ms-settings:fonts",
                "region": "ms-settings:regionformatting",
                "language": "ms-settings:language",
                "date": "ms-settings:dateandtime",
                "update": "ms-settings:windowsupdate",
                "security": "ms-settings:windowsdefender",
                "troubleshoot": "ms-settings:troubleshoot",
                "about": "ms-settings:about",
                "devices": "ms-settings:devices",
                "mouse": "ms-settings:mousetouchpad",
                "touchpad": "ms-settings:devices-touchpad",
                "typing": "ms-settings:typing",
                "pen": "ms-settings:pen",
                "autoplay": "ms-settings:autoplay",
                "usb": "ms-settings:usb",
            }
            uri = page_map.get(page.lower().strip(), f"ms-settings:{page}" if page else "ms-settings:")
            subprocess.Popen(f'start "" "{uri}"', shell=True)
            return {"success": True, "page": page or "main", "uri": uri}
        except Exception as e:
            log.error("open_settings_failed", page=page, error=str(e))
            return {"success": False, "error": str(e)}

    def open_url(self, url: str) -> Dict[str, Any]:
        """Open a URL in the default browser."""
        import subprocess
        import webbrowser
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            return {"success": True, "url": url}
        except Exception as e:
            try:
                subprocess.Popen(f'start "" "{url}"', shell=True)
                return {"success": True, "url": url}
            except Exception as e2:
                log.error("open_url_failed", url=url, error=str(e2))
                return {"success": False, "error": str(e2)}

    def open_folder(self, folder_path: str) -> Dict[str, Any]:
        """Open a specific folder in File Explorer. Supports absolute paths, ~ for home, and special names."""
        import subprocess
        from pathlib import Path
        try:
            path = folder_path.strip()
            # Handle special folder names
            folder_map = {
                "desktop": str(Path.home() / "Desktop"),
                "downloads": str(Path.home() / "Downloads"),
                "documents": str(Path.home() / "Documents"),
                "pictures": str(Path.home() / "Pictures"),
                "music": str(Path.home() / "Music"),
                "videos": str(Path.home() / "Videos"),
                "home": str(Path.home()),
            }
            key = path.lower().strip()
            if key in folder_map:
                resolved = folder_map[key]
            elif key.startswith("~"):
                resolved = str(Path.home() / key[1:].lstrip("\\/"))
            else:
                resolved = path

            expanded = Path(resolved).expanduser().resolve()
            if expanded.exists() and expanded.is_dir():
                subprocess.Popen(f'explorer "{expanded}"', shell=True)
                return {"success": True, "folder": str(expanded)}
            # If path doesn't exist, try as a subfolder of Desktop
            desktop_path = Path.home() / "Desktop" / path
            if desktop_path.exists() and desktop_path.is_dir():
                subprocess.Popen(f'explorer "{desktop_path}"', shell=True)
                return {"success": True, "folder": str(desktop_path)}
            return {"success": False, "error": f"Folder not found: {path}"}
        except Exception as e:
            log.error("open_folder_failed", path=folder_path, error=str(e))
            return {"success": False, "error": str(e)}

    def find_text_on_screen(self, text: str) -> Dict[str, Any]:
        """Search visible windows for a text string and return the clickable region."""
        import pygetwindow as gw
        try:
            windows = gw.getAllWindows()
            results = []
            for w in windows:
                if w.title and w.visible and text.lower() in w.title.lower():
                    results.append({
                        "title": w.title,
                        "left": w.left, "top": w.top,
                        "width": w.width, "height": w.height,
                        "center": (w.left + w.width // 2, w.top + w.height // 2),
                    })
            return {
                "success": len(results) > 0,
                "matches": results,
                "count": len(results),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


desktop_service = DesktopService()
