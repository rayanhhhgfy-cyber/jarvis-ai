# ====================================================================
# JARVIS OMEGA — Command Interpreter
# ====================================================================
"""
Server-side natural language → OS command interpreter.
Detects device-control intent from user messages and generates
the corresponding Windows shell commands. This runs BEFORE the LLM
so we don't rely on the model to produce structured <run_os_command> tags.
"""

from __future__ import annotations

import re
from typing import Optional, List, Tuple

from shared.logger import get_logger

log = get_logger("command_interpreter")


class CommandInterpreter:
    """
    Pattern-based NLU that maps natural language requests to Windows
    shell commands. Returns None when no OS action is detected.
    """

    # ---- App Launch Patterns ----
    # Maps spoken app names → Windows launch commands
    APP_REGISTRY = {
        # System apps
        "settings": "start ms-settings:",
        "control panel": "start control",
        "task manager": "start taskmgr",
        "device manager": "start devmgmt.msc",
        "file explorer": "start explorer",
        "explorer": "start explorer",
        "files": "start explorer",
        "calculator": "start calc",
        "notepad": "notepad",
        "paint": "start mspaint",
        "cmd": "start cmd",
        "command prompt": "start cmd",
        "terminal": "start wt",
        "powershell": "start powershell",
        "registry editor": "start regedit",
        "disk management": "start diskmgmt.msc",
        "system information": "start msinfo32",
        "resource monitor": "start resmon",
        "performance monitor": "start perfmon",
        "event viewer": "start eventvwr",
        "services": "start services.msc",
        "snipping tool": "start snippingtool",
        "screen snip": "start snippingtool",
        "magnifier": "start magnify",
        "remote desktop": "start mstsc",
        "sound settings": "start ms-settings:sound",
        "display settings": "start ms-settings:display",
        "bluetooth settings": "start ms-settings:bluetooth",
        "wifi settings": "start ms-settings:network-wifi",
        "network settings": "start ms-settings:network",
        "windows update": "start ms-settings:windowsupdate",
        "storage settings": "start ms-settings:storagesense",
        "apps settings": "start ms-settings:appsfeatures",
        "personalization": "start ms-settings:personalization",
        "date and time": "start ms-settings:dateandtime",
        "about": "start ms-settings:about",

        # Browsers
        "chrome": "start chrome",
        "google chrome": "start chrome",
        "firefox": "start firefox",
        "edge": "start msedge",
        "microsoft edge": "start msedge",
        "brave": "start brave",
        "opera": "start opera",

        # Productivity
        "word": "start winword",
        "microsoft word": "start winword",
        "excel": "start excel",
        "microsoft excel": "start excel",
        "powerpoint": "start powerpnt",
        "outlook": "start outlook",
        "teams": "start msteams:",
        "microsoft teams": "start msteams:",
        "onenote": "start onenote",
        "visual studio code": "start code",
        "vscode": "start code",
        "vs code": "start code",

        # Media
        "spotify": "start spotify:",
        "vlc": "start vlc",
        "media player": "start wmplayer",
        "photos": "start ms-photos:",

        # Communication
        "discord": "start discord:",
        "telegram": "start telegram:",
        "whatsapp": "start whatsapp:",
        "slack": "start slack:",
        "zoom": "start zoom",
        "skype": "start skype:",

        # Gaming
        "steam": "start steam:",
        "epic games": 'start "" "C:\\Program Files (x86)\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe"',

        # Development
        "git bash": 'start "" "C:\\Program Files\\Git\\git-bash.exe"',
        "postman": "start postman:",
        "docker desktop": "start docker",
    }

    # ---- Settings-specific URI mappings ----
    SETTINGS_MAP = {
        "wifi": "start ms-settings:network-wifi",
        "bluetooth": "start ms-settings:bluetooth",
        "display": "start ms-settings:display",
        "brightness": "start ms-settings:display",
        "sound": "start ms-settings:sound",
        "volume": "start ms-settings:sound",
        "audio": "start ms-settings:sound",
        "notifications": "start ms-settings:notifications",
        "battery": "start ms-settings:batterysaver",
        "power": "start ms-settings:powersleep",
        "storage": "start ms-settings:storagesense",
        "privacy": "start ms-settings:privacy",
        "mouse": "start ms-settings:mousetouchpad",
        "keyboard": "start ms-settings:typing",
        "accounts": "start ms-settings:yourinfo",
        "updates": "start ms-settings:windowsupdate",
        "windows update": "start ms-settings:windowsupdate",
        "default apps": "start ms-settings:defaultapps",
        "apps": "start ms-settings:appsfeatures",
        "background": "start ms-settings:personalization-background",
        "lock screen": "start ms-settings:lockscreen",
        "themes": "start ms-settings:themes",
        "colors": "start ms-settings:colors",
        "taskbar": "start ms-settings:taskbar",
        "fonts": "start ms-settings:fonts",
        "region": "start ms-settings:regionformatting",
        "language": "start ms-settings:regionlanguage",
        "date": "start ms-settings:dateandtime",
        "time": "start ms-settings:dateandtime",
        "vpn": "start ms-settings:network-vpn",
        "proxy": "start ms-settings:network-proxy",
        "night light": "start ms-settings:nightlight",
        "camera": "start ms-settings:privacy-webcam",
        "microphone": "start ms-settings:privacy-microphone",
    }

    def interpret(self, message: str) -> Optional[List[Tuple[str, str]]]:
        """
        Analyze a user message and extract OS commands.
        Returns a list of (description, command) tuples, or None.
        """
        msg = message.strip().lower()

        # Check all pattern categories
        results = []

        # 1. Open / Launch app
        result = self._check_open_app(msg)
        if result:
            results.append(result)

        # 2. Settings navigation
        if not results:
            result = self._check_settings(msg)
            if result:
                results.append(result)

        # 3. URL/Site operations (before file ops to catch "search X on youtube")
        if not results:
            result = self._check_open_url(msg, message)
            if result:
                results.append(result)

        # 4. File/folder operations
        if not results:
            result = self._check_file_operations(msg, message)
            if result:
                results.append(result)

        # 5. System info commands
        if not results:
            result = self._check_system_info(msg)
            if result:
                results.append(result)

        # 6. Process management
        if not results:
            result = self._check_process_management(msg, message)
            if result:
                results.append(result)

        # 7. System control (shutdown, restart, etc.)
        if not results:
            result = self._check_system_control(msg)
            if result:
                results.append(result)

        # 8. Network operations
        if not results:
            result = self._check_network(msg)
            if result:
                results.append(result)

        # 9. Direct command execution ("run command ...", "execute ...")
        if not results:
            result = self._check_direct_command(msg, message)
            if result:
                results.append(result)

        # 10. Volume control
        if not results:
            result = self._check_volume_control(msg)
            if result:
                results.append(result)

        if results:
            log.info("commands_interpreted", count=len(results),
                     descriptions=[r[0] for r in results])
            return results
        return None

    # ====================================================================
    # Pattern Matchers
    # ====================================================================

    def _check_open_app(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect 'open X', 'launch X', 'start X' patterns."""
        patterns = [
            r"(?:open|launch|start|run|fire up|bring up|pull up|show me)\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app|\s+application|\s+program|\s+please|\s+for me)?$",
        ]

        for pattern in patterns:
            match = re.search(pattern, msg)
            if match:
                app_name = match.group(1).strip().rstrip(".")
                # Check direct match in registry
                if app_name in self.APP_REGISTRY:
                    return (f"Opening {app_name}", self.APP_REGISTRY[app_name])
                # Check partial matches
                for key, cmd in self.APP_REGISTRY.items():
                    if key in app_name or app_name in key:
                        return (f"Opening {key}", cmd)

        return None

    def _check_settings(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect settings-related requests."""
        # "open settings" -> generic settings
        if re.search(r"(?:open|go to|show|launch)\s+(?:the\s+)?settings", msg):
            # Check if a specific settings page is requested
            for key, cmd in self.SETTINGS_MAP.items():
                if key in msg:
                    return (f"Opening {key} settings", cmd)
            return ("Opening Windows Settings", "start ms-settings:")

        # "change/adjust/modify X settings"
        settings_match = re.search(
            r"(?:change|adjust|modify|configure|set|toggle|turn on|turn off|enable|disable)\s+(?:the\s+)?(\w+(?:\s+\w+)?)",
            msg,
        )
        if settings_match:
            target = settings_match.group(1).strip()
            for key, cmd in self.SETTINGS_MAP.items():
                if key in target or target in key:
                    return (f"Opening {key} settings", cmd)

        return None

    def _check_file_operations(self, msg: str, original: str) -> Optional[Tuple[str, str]]:
        """Detect file/folder creation, deletion, listing."""
        # Create folder
        match = re.search(
            r"(?:create|make|new)\s+(?:a\s+)?(?:folder|directory|dir)(?:\s+(?:called|named))?\s+[\"']?(.+?)[\"']?\s*$",
            msg,
        )
        if match:
            folder = match.group(1).strip().rstrip(".")
            return (f"Creating folder '{folder}'", f'mkdir "{folder}"')

        # Delete file/folder
        match = re.search(
            r"(?:delete|remove|erase|rm)\s+(?:the\s+)?(?:file|folder|directory)?\s*[\"']?(.+?)[\"']?\s*$",
            msg,
        )
        if match:
            target = match.group(1).strip().rstrip(".")
            return (f"Deleting '{target}'", f'del /q "{target}" 2>nul & rmdir /s /q "{target}" 2>nul & echo Done')

        # List files
        if re.search(r"(?:list|show|display|what(?:'s| is| are))\s+(?:the\s+)?(?:files|folders|contents|directory)", msg):
            path_match = re.search(r"(?:in|of|at|from)\s+[\"']?(.+?)[\"']?\s*$", msg)
            path = path_match.group(1).strip().rstrip(".") if path_match else "."
            return (f"Listing files in '{path}'", f'dir "{path}"')

        # Find files
        match = re.search(r"(?:find|search|locate)\s+(?:the\s+)?(?:file|files)?\s*[\"']?(.+?)[\"']?\s*$", msg)
        if match:
            pattern = match.group(1).strip().rstrip(".")
            return (f"Searching for '{pattern}'", f'dir /s /b "*{pattern}*"')

        return None

    def _check_system_info(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect system information queries."""
        if re.search(r"(?:what(?:'s| is)|show|tell me|display|get)\s+(?:my\s+)?(?:computer|system|device)\s*(?:name|info|information)?", msg):
            return ("Getting system information", "systeminfo | findstr /B /C:\"OS Name\" /C:\"OS Version\" /C:\"System Manufacturer\" /C:\"System Model\" /C:\"Total Physical Memory\"")

        if re.search(r"(?:what(?:'s| is)|show|tell|get)\s+(?:my\s+)?(?:ip|ip address)", msg):
            return ("Getting IP address", "ipconfig | findstr /i \"IPv4\"")

        if re.search(r"(?:what(?:'s| is)|show|check|tell)\s+(?:my\s+)?(?:username|user name|who am i|whoami)", msg):
            return ("Getting username", "whoami")

        if re.search(r"(?:how much|show|check|what(?:'s| is))\s+(?:my\s+)?(?:disk|storage|drive)\s*(?:space|usage)?", msg):
            return ("Checking disk usage", "wmic logicaldisk get size,freespace,caption")

        if re.search(r"(?:how much|show|check|what(?:'s| is))\s+(?:my\s+)?(?:ram|memory)\s*(?:usage|available)?", msg):
            return ("Checking memory usage", 'systeminfo | findstr /C:"Total Physical Memory" /C:"Available Physical Memory"')

        if re.search(r"(?:what(?:'s| is)|check|show)\s+(?:my\s+)?(?:battery|power)\s*(?:level|status|percentage)?", msg):
            return ("Checking battery status", "powercfg /batteryreport /output battery.html & type battery.html | findstr /i \"FULL\\|REMAINING\"")

        if re.search(r"(?:what|which)\s+(?:windows|os)\s+(?:version|edition)", msg):
            return ("Getting OS version", "winver")

        if re.search(r"(?:system|computer|device)\s+(?:specs|specifications|hardware)", msg):
            return ("Getting system specs", "systeminfo")

        return None

    def _check_process_management(self, msg: str, original: str) -> Optional[Tuple[str, str]]:
        """Detect process kill/list operations."""
        # Kill/close/stop an app
        match = re.search(r"(?:kill|close|stop|end|terminate|quit|exit)\s+(?:the\s+)?(.+?)(?:\s+app|\s+process|\s+program|\s+please)?$", msg)
        if match:
            target = match.group(1).strip().rstrip(".")
            # Map common names to process names
            process_map = {
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "firefox": "firefox.exe",
                "edge": "msedge.exe",
                "notepad": "notepad.exe",
                "word": "WINWORD.EXE",
                "excel": "EXCEL.EXE",
                "powerpoint": "POWERPNT.EXE",
                "discord": "Discord.exe",
                "spotify": "Spotify.exe",
                "teams": "ms-teams.exe",
                "slack": "slack.exe",
                "steam": "steam.exe",
                "vscode": "Code.exe",
                "vs code": "Code.exe",
                "visual studio code": "Code.exe",
                "explorer": "explorer.exe",
                "vlc": "vlc.exe",
                "zoom": "Zoom.exe",
                "telegram": "Telegram.exe",
            }
            proc = process_map.get(target, f"{target}.exe")
            return (f"Closing {target}", f"taskkill /IM {proc} /F")

        # List running processes
        if re.search(r"(?:list|show|what(?:'s| is| are))\s+(?:running|active|open)\s+(?:processes|apps|applications|programs|tasks)", msg):
            return ("Listing running processes", "tasklist /FO TABLE | head -30")

        return None

    def _check_system_control(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect shutdown, restart, sleep, lock commands."""
        if re.search(r"(?:shut\s*down|power\s*off|turn\s*off)\s+(?:the\s+)?(?:computer|pc|system|workstation|device)", msg):
            return ("Shutting down the workstation", "shutdown /s /t 10 /c \"JARVIS: Shutting down in 10 seconds, Sir.\"")

        if re.search(r"(?:restart|reboot)\s+(?:the\s+)?(?:computer|pc|system|workstation|device)", msg):
            return ("Restarting the workstation", "shutdown /r /t 10 /c \"JARVIS: Restarting in 10 seconds, Sir.\"")

        if re.search(r"(?:lock)\s+(?:the\s+)?(?:computer|pc|screen|system|workstation|device)", msg):
            return ("Locking the workstation", "rundll32.exe user32.dll,LockWorkStation")

        if re.search(r"(?:sleep|hibernate|suspend)\s+(?:the\s+)?(?:computer|pc|system|workstation)?", msg):
            return ("Putting system to sleep", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

        if re.search(r"(?:cancel|abort|stop)\s+(?:the\s+)?(?:shut\s*down|shutdown|restart|reboot)", msg):
            return ("Cancelling shutdown", "shutdown /a")

        return None

    def _check_network(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect network diagnostic commands."""
        match = re.search(r"ping\s+(.+?)$", msg)
        if match:
            target = match.group(1).strip().rstrip(".")
            return (f"Pinging {target}", f"ping {target} -n 4")

        if re.search(r"(?:network|internet)\s+(?:status|connectivity|connection)", msg):
            return ("Checking network connectivity", "ping 8.8.8.8 -n 2 & ipconfig | findstr /i \"IPv4\"")

        if re.search(r"(?:wifi|wireless)\s+(?:networks|connections|available)", msg):
            return ("Scanning WiFi networks", "netsh wlan show networks")

        if re.search(r"(?:connected|current)\s+(?:wifi|network)", msg):
            return ("Checking current WiFi", "netsh wlan show interfaces")

        return None

    def _check_open_url(self, msg: str, original: str) -> Optional[Tuple[str, str]]:
        """Detect requests to open websites and search on sites like YouTube."""

        # --- YouTube search ---
        # "search for X on youtube", "youtube search X", "open youtube and search X"
        yt_search = re.search(
            r"(?:search|look|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+youtube",
            msg, re.IGNORECASE,
        )
        if yt_search:
            query = yt_search.group(1).strip().rstrip(".")
            encoded = query.replace(" ", "+")
            return (
                f"Searching YouTube for '{query}'",
                f'start "" "https://www.youtube.com/results?search_query={encoded}"',
            )

        yt_search2 = re.search(
            r"(?:open|go to)\s+youtube\s+and\s+(?:search|look|find)\s+(?:for\s+)?(.+?)$",
            msg, re.IGNORECASE,
        )
        if yt_search2:
            query = yt_search2.group(1).strip().rstrip(".")
            encoded = query.replace(" ", "+")
            return (
                f"Searching YouTube for '{query}'",
                f'start "" "https://www.youtube.com/results?search_query={encoded}"',
            )

        yt_search3 = re.search(
            r"youtube\s+(?:search\s+)?(.+?)$",
            msg, re.IGNORECASE,
        )
        if yt_search3:
            query = yt_search3.group(1).strip().rstrip(".")
            encoded = query.replace(" ", "+")
            return (
                f"Searching YouTube for '{query}'",
                f'start "" "https://www.youtube.com/results?search_query={encoded}"',
            )

        # --- Google search ---
        g_search = re.search(
            r"(?:search|look|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+google",
            msg, re.IGNORECASE,
        )
        if g_search:
            query = g_search.group(1).strip().rstrip(".")
            encoded = query.replace(" ", "+")
            return (
                f"Searching Google for '{query}'",
                f'start "" "https://www.google.com/search?q={encoded}"',
            )

        # "open youtube" / "go to google.com"
        match = re.search(
            r"(?:open|go to|navigate to|browse|visit)\s+(?:the\s+)?(?:website\s+)?(?:of\s+)?([\w.-]+\.[\w]+)",
            msg,
        )
        if match:
            url = match.group(1)
            if not url.startswith("http"):
                url = f"https://{url}"
            return (f"Opening {url}", f'start "" "{url}"')

        # Common sites without TLD
        site_map = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "gmail": "https://mail.google.com",
            "twitter": "https://twitter.com",
            "x": "https://x.com",
            "reddit": "https://www.reddit.com",
            "linkedin": "https://www.linkedin.com",
            "facebook": "https://www.facebook.com",
            "instagram": "https://www.instagram.com",
            "amazon": "https://www.amazon.com",
            "stackoverflow": "https://stackoverflow.com",
            "chatgpt": "https://chat.openai.com",
            "netflix": "https://www.netflix.com",
            "twitch": "https://www.twitch.tv",
        }

        site_match = re.search(r"(?:open|go to|browse)\s+(?:the\s+)?(\w+)", msg)
        if site_match:
            site_name = site_match.group(1)
            if site_name in site_map:
                return (f"Opening {site_name}", f'start "" "{site_map[site_name]}"')

        return None

    def _check_direct_command(self, msg: str, original: str) -> Optional[Tuple[str, str]]:
        """Detect explicit 'run command X' or 'execute X' patterns."""
        patterns = [
            r"(?:run|execute|perform)\s+(?:the\s+)?(?:command|cmd)\s*[:\s]+(.+)$",
            r"(?:run|execute)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, msg)
            if match:
                cmd = match.group(1).strip().strip('"\'').rstrip(".")
                # Avoid matching things like "run a diagnostic" which are not literal commands
                # Only match if it looks like an actual shell command
                if any(c in cmd for c in ["/", "\\", ".", "-", "|", ">", "&", "="]) or len(cmd.split()) <= 3:
                    # Use original case for the command
                    orig_match = re.search(pattern, original.strip().lower())
                    if orig_match:
                        # Extract from original preserving case
                        start = original.lower().find(cmd[:10].lower())
                        if start >= 0:
                            cmd = original[start:start + len(cmd)].strip()
                    return (f"Executing: {cmd}", cmd)

        return None

    def _check_volume_control(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect volume control requests (uses PowerShell/nircmd)."""
        if re.search(r"(?:mute|silence|quiet)", msg):
            return (
                "Muting audio",
                'powershell -c "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
            )

        if re.search(r"(?:unmute|unsilence)", msg):
            return (
                "Unmuting audio",
                'powershell -c "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
            )

        if re.search(r"(?:volume|turn)\s+(?:up|louder|higher|increase)", msg):
            return (
                "Increasing volume",
                'powershell -c "1..5 | ForEach-Object { (New-Object -ComObject WScript.Shell).SendKeys([char]175) }"',
            )

        if re.search(r"(?:volume|turn)\s+(?:down|lower|decrease|quieter|softer)", msg):
            return (
                "Decreasing volume",
                'powershell -c "1..5 | ForEach-Object { (New-Object -ComObject WScript.Shell).SendKeys([char]174) }"',
            )

        return None


# Global singleton
command_interpreter = CommandInterpreter()
