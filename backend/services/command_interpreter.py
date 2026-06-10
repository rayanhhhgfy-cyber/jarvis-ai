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
        "messenger": 'start "" "https://www.messenger.com"',
        "facebook messenger": 'start "" "https://www.messenger.com"',
        "messages": 'start "" "https://www.messenger.com"',
        "messeges": 'start "" "https://www.messenger.com"',  # common misspelling
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

    # ---- Site URL Map (shared by _check_open_url, _check_social_send, _check_open_social_chat) ----
    SITE_MAP = {
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
        "messenger": "https://www.messenger.com",
        "messeges": "https://www.messenger.com",
        "facebook messenger": "https://www.messenger.com",
        "amazon": "https://www.amazon.com",
        "stackoverflow": "https://stackoverflow.com",
        "chatgpt": "https://chat.openai.com",
        "netflix": "https://www.netflix.com",
        "twitch": "https://www.twitch.tv",
        "instagram direct": "https://www.instagram.com/direct/inbox",
        "instagram dm": "https://www.instagram.com/direct/inbox",
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

    def _split_commands(self, msg: str) -> List[str]:
        """Split a multi-command message into individual command segments."""
        # Don't split if "and" connects a file creation to its content
        if re.search(
            r"(?:create|make|write|generate|new)\s+(?:a\s+)?file\s+.+?\s+and\s+"
            r"(?:put|add|write|insert|include|place|save)\s+",
            msg, re.IGNORECASE,
        ):
            return [msg]

        # Don't split Instagram DM patterns ("open instagram and send a message")
        if re.search(
            r"(?:open|launch|go\s+to)\s+instagram\s+and\s+"
            r"(?:send|message|dm)\s+(?:a\s+)?(?:message|dm|someone\s+a\s+message)",
            msg, re.IGNORECASE,
        ):
            return [msg]

        separators = [
            r"\s+and\s+then\s+",
            r"\s+and also\s+",
            r"\s+and\s+",
            r",\s*and\s+",
            r",\s*",
            r"\s*;\s*",
        ]
        for sep in separators:
            parts = re.split(sep, msg)
            if len(parts) > 1:
                return [p.strip() for p in parts if p.strip()]
        return [msg]

    def interpret(self, message: str) -> Optional[List[Tuple[str, str]]]:
        """
        Analyze a user message and extract OS commands.
        Supports multi-command messages split by 'and', commas, etc.
        Returns a list of (description, command) tuples, or None.
        """
        msg = message.strip().lower()
        context = {"opened": ""}

        results = []

        segments = self._split_commands(msg)
        if len(segments) > 1:
            log.info("multi_command_detected", segments=len(segments))
            for segment in segments:
                seg_results = self._interpret_single(segment, message, context)
                if seg_results:
                    results.extend(seg_results)
                    # Track what was opened in context
                    for desc, _ in seg_results:
                        context["opened"] += " " + desc.lower()
            if results:
                log.info("commands_interpreted", count=len(results),
                         descriptions=[r[0] for r in results])
                return results

        results = self._interpret_single(msg, message, context)
        if results:
            log.info("commands_interpreted", count=len(results),
                     descriptions=[r[0] for r in results])
            return results
        return None

    def _interpret_single(self, msg: str, original: str, context: Optional[dict] = None) -> List[Tuple[str, str]]:
        """Analyze a single command segment and return OS commands."""
        context = context or {"opened": ""}
        results = []

        checkers = [
            lambda m: self._check_instagram_dm(m, context),
            lambda m: self._check_open_social_chat(m, context),
            lambda m: self._check_open_app(m, context),
            lambda m: self._check_settings(m),
            lambda m: self._check_open_url(m, original),
            lambda m: self._check_file_operations(m, original),
            lambda m: self._check_system_info(m),
            lambda m: self._check_process_management(m, original),
            lambda m: self._check_system_control(m),
            lambda m: self._check_network(m),
            lambda m: self._check_direct_command(m, original),
            lambda m: self._check_social_send(m, original, context),
            lambda m: self._check_navigate_within_site(m, context),
            lambda m: self._check_desktop_interaction(m),
            lambda m: self._check_browser_interaction(m),
            lambda m: self._check_volume_control(m),
        ]

        for checker in checkers:
            result = checker(msg)
            if result:
                results.append(result)
                break

        return results

    # ====================================================================
    # Pattern Matchers
    # ====================================================================

    def _check_open_app(self, msg: str, context: Optional[dict] = None) -> Optional[Tuple[str, str]]:
        """Detect 'open X', 'launch X', 'start X' patterns."""
        context = context or {"opened": ""}
        patterns = [
            r"(?:open|launch|start|run|fire up|bring up|pull up|show me)\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app|\s+application|\s+program|\s+please|\s+for me)?$",
        ]

        for pattern in patterns:
            match = re.search(pattern, msg)
            if match:
                app_name = match.group(1).strip().rstrip(".")

                # Context-aware: if "messeges"/"messages" said after "instagram", open Instagram DMs
                prev_opened = context.get("opened", "").lower()
                if app_name in ("messeges", "messages", "messenger", "facebook messenger") and "instagram" in prev_opened:
                    return (f"Opening Instagram messages", f'start "" "https://www.instagram.com/direct/inbox"')

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

        # Helper: create a file on desktop via PowerShell
        def _create_file_cmd(filename: str, content: str = "") -> tuple:
            desktop = r"%USERPROFILE%\Desktop"
            if content:
                safe = content.replace("'", "''").replace('"', '\\"')
                return (
                    f"Creating file '{filename}' on desktop",
                    f'powershell -Command "Set-Content -Path \\\"{desktop}\\{filename}\\\" -Value \\\"{safe}\\\""',
                )
            return (
                f"Creating file '{filename}' on desktop",
                f'powershell -Command "New-Item -Path \\\"{desktop}\\{filename}\\\" -ItemType File -Force"',
            )

        # ---- Create file on desktop (with simple content or empty) ----
        # Normalize: collapse "desk top" → "desktop", then "on/in/to my/the desktop" → "@DESKTOP"
        normal = re.sub(r"\bdesk\s+top\b", "desktop", msg, flags=re.IGNORECASE)
        normal = re.sub(r"\b(?:on|in|to)\s+(?:my|the)\s+desktop\b", " @DESKTOP ", normal, flags=re.IGNORECASE)
        normal = re.sub(r"\b(?:on|in|to)\s+desktop\b", " @DESKTOP ", normal, flags=re.IGNORECASE)

        # Create file with CONTENT: "create a file called X with content Y"
        m = re.search(
            r"(?:create|make|write|generate)\s+(?:a\s+)?(?:file|text\s*file)"
            r"(?:\s+@DESKTOP)?"
            r"(?:\s+(?:called|named|titled))?\s*[\"']?(.+?)[\"']?"
            r"(?:\s+@DESKTOP)?"
            r"\s+(?:with|that\s+says|containing|and\s+put\s+in\s+it)\s+(?:content|text|data|the\s+words|a\s+message)?\s*[\"']?(.+?)[\"']?\s*$",
            normal, re.IGNORECASE | re.DOTALL,
        )
        if m:
            filename = m.group(1).strip().rstrip(".").strip("'\" ")
            content = m.group(2).strip().rstrip(".").strip("'\" ")
            if filename:
                # If content looks like a generation request ("5 usernames", "100 names"), fall through to LLM
                if not re.search(r"^\d+\s+\w+", content):
                    return _create_file_cmd(filename, content)

        # Create file WITHOUT content (empty file): "create a file called X @DESKTOP"
        m = re.search(
            r"(?:create|make|write|generate|new)\s+(?:a\s+)?(?:file|text\s*file)"
            r"(?:\s+@DESKTOP)?"
            r"(?:\s+(?:called|named|titled))?\s*[\"']?(.+?)[\"']?"
            r"(?:\s+@DESKTOP)?\s*$",
            normal, re.IGNORECASE,
        )
        if m:
            filename = m.group(1).strip().rstrip(".").strip("'\" ")
            if filename and not re.search(r"(?:folder|directory|dir|and\s|\bput\b|\bwith\s)", filename, re.IGNORECASE):
                # Reject filenames that are just locator prepositions (captured by greedy regex)
                if not re.search(r"^\s*(?:in|on|at|to|for|the|my|this)\s+", filename, re.IGNORECASE):
                    return _create_file_cmd(filename)

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
        match = re.search(r"\b(?:kill|close|stop|end|terminate|quit|exit)\s+(?:the\s+)?(.+?)(?:\s+app|\s+process|\s+program|\s+please)?$", msg)
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
        """Detect shutdown, restart, sleep, lock, wallpaper commands."""
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

        # --- Web Wallpaper (download from internet) ---
        web_wl = re.search(
            r"(?:grab|find|download|get|search|fetch|take)\s+"
            r"(?:a|an|the|me|some|that)\s+"
            r"(.+?)"
            r"(?:\s+(?:and\s+)?(?:set|put|make|use|apply)\s+(?:it\s+)?"
            r"(?:as|for|as\s+my)\s+(?:a\s+)?(?:wallpaper|desktop|background))",
            msg, re.IGNORECASE,
        )
        if web_wl:
            query = (web_wl.group(1) or web_wl.group(2) or "").strip().strip(",").strip()
            query = query.replace('"', "").replace("'", "").replace("`", "")
            if not query or query.lower() in ("a", "an", "the", "some"):
                return (
                    "Searching for a wallpaper from the web",
                    'python scripts/set_wallpaper_from_web.py "high resolution wallpaper"',
                )
            return (
                f"Searching for '{query}' wallpaper from web",
                f'python scripts/set_wallpaper_from_web.py "{query}"',
            )

        # --- Wallpaper (local) ---
        wl = re.search(
            r"(?:change|set|apply)\s+(?:the\s+)?(?:wallpaper|desktop\s+background|background)",
            msg,
        )
        if wl:
            path_match = re.search(r"(?:to|as|using)\s+[\"']?(.+?)[\"']?\s*$", msg)
            if path_match:
                img_path = path_match.group(1).strip().rstrip(".")
                return (
                    f"Changing wallpaper to '{img_path}'",
                    f'python -c "import ctypes; r=ctypes.windll.user32.SystemParametersInfoW(20,0,r\'{img_path}\',3); print(\'Wallpaper updated\' if r else \'Failed\'); exit(0 if r else 1)"',
                )

            return (
                "Setting a random Windows wallpaper",
                'python -c "import ctypes,random,os,pathlib; p=list(pathlib.Path(os.environ[\'WINDIR\']+\'\\\\Web\\\\Wallpaper\').rglob(\'*.jpg\'));'
                ' i=str(random.choice(p)) if p else None;'
                ' r=ctypes.windll.user32.SystemParametersInfoW(20,0,i,3) if i else 0;'
                ' print(\'Wallpaper set to:\'+i if r else \'No wallpapers found\');'
                ' exit(0 if r else 1)"',
            )

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
        site_name = re.search(r"(?:open|go to|browse)\s+(?:the\s+)?(\w+)", msg)
        if site_name:
            name = site_name.group(1)
            if name in self.SITE_MAP:
                return (f"Opening {name}", f'start "" "{self.SITE_MAP[name]}"')

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

    def _check_open_social_chat(self, msg: str, context: Optional[dict] = None) -> Optional[Tuple[str, str]]:
        """Detect 'open {platform} on {contact} chat' or 'open {contact} on {platform}'."""
        context = context or {"opened": ""}
        prev_opened = context.get("opened", "").lower()
        # Find "on/in {contact} chat" anywhere in the message
        chat_match = re.search(r"(?:on|in)\s+(.+?)\s+(?:chat|conversation|dm)", msg, re.IGNORECASE)
        if not chat_match:
            return None
        # Extract everything before "on {contact} chat"
        before = msg[:chat_match.start()].strip()
        # Strip leading "open/go to/launch"
        before = re.sub(r"^(?:open|go to|launch)\s+", "", before, flags=re.IGNORECASE).strip()
        # Try to match a known platform name from SITE_MAP (longest match first)
        matched_platform = None
        for name in sorted(self.SITE_MAP, key=len, reverse=True):
            if name in before.lower():
                matched_platform = name
                break
        if matched_platform:
            # Context-aware: if platform is messenger-ish and Instagram was opened, go to Instagram DM
            if matched_platform in ("messeges", "messages", "messenger", "facebook messenger") and "instagram" in prev_opened:
                return (f"Opening Instagram messages", f'start "" "https://www.instagram.com/direct/inbox"')
            return (f"Opening {matched_platform}", f'start "" "{self.SITE_MAP[matched_platform]}"')
        return None

    def _check_social_send(self, msg: str, original: str, context: Optional[dict] = None) -> Optional[Tuple[str, str]]:
        """Detect 'send message to contact on platform' patterns and open the platform."""
        context = context or {"opened": ""}
        prev_opened = context.get("opened", "").lower()
        send_match = re.search(
            r"(?:send|message|dm)\s+(.+?)\s+(?:to|for)\s+(.+?)\s+(?:on|in|via)\s+(.+?)$",
            msg, re.IGNORECASE,
        )
        if send_match:
            contact = send_match.group(2).strip().rstrip(".")
            platform = send_match.group(3).strip().rstrip(".")
            platform_url = self.SITE_MAP.get(platform.lower())
            if platform_url:
                return (f"Opening {platform} to message {contact}", f'start "" "{platform_url}"')

        # "open {platform} and message {contact}"
        open_and_send = re.search(
            r"(?:open|launch)\s+(.+?)\s+and\s+(?:send|message|dm)\s+(.+?)\s+(?:to|for)\s+(.+?)$",
            msg, re.IGNORECASE,
        )
        if open_and_send:
            platform = open_and_send.group(1).strip().rstrip(".")
            platform_url = self.SITE_MAP.get(platform.lower())
            if platform_url:
                return (f"Opening {platform}", f'start "" "{platform_url}"')

        # "send {message}" (no platform specified) — check context first, default to Messenger
        bare_send = re.search(r"^send\s+(.+?)$", msg, re.IGNORECASE)
        if bare_send:
            msg_text = bare_send.group(1).strip().rstrip(".")
            # If Instagram was recently opened, send via Instagram DM instead of Messenger
            if "instagram" in prev_opened:
                return (
                    f"Opening Instagram messages to send: {msg_text[:50]}",
                    f'start "" "https://www.instagram.com/direct/inbox"',
                )
            return (
                f"Opening Messenger to send: {msg_text[:50]}",
                f'start "" "https://www.messenger.com"',
            )

        return None

    def _check_instagram_dm(self, msg: str, context: Optional[dict] = None) -> Optional[Tuple[str, str]]:
        """Detect Instagram DM intent and return structured commands."""
        # "send a dm to [user] on instagram"
        m = re.search(r"(?:send|message|dm)\s+(?:a\s+)?(?:dm|message)?\s*(?:to\s+)?(\w+)\s+(?:on|via|through)\s+instagram", msg, re.IGNORECASE)
        if m:
            user = m.group(1)
            return (f"Sending Instagram DM to {user}", f"instagram_dm_send|{user}|")
        # Handle split segments: "open instagram" then "send a message"
        context = context or {"opened": ""}
        prev = context.get("opened", "").lower()
        if "instagram" in prev or msg == "send a message":
            m = re.search(r"send\s+(?:a\s+)?(?:message|dm)\s*(?:on|in|via|through)?\s*instagram?", msg, re.IGNORECASE)
            if m:
                return ("Sending Instagram DM to first contact", "instagram_dm_send||")
        # "send someone a message on instagram" / "send a message on instagram"
        m = re.search(r"(?:send|message|dm)\s+(?:.+?\s+)?(?:message|dm)\s+(?:on|in|via|through)\s+instagram", msg, re.IGNORECASE)
        if m:
            return ("Sending Instagram DM to first contact", "instagram_dm_send||")
        # "send [message] on instagram"
        m = re.search(r"^send\s+(.+?)\s+(?:on|in|via|through)\s+instagram$", msg, re.IGNORECASE)
        if m:
            return (f"Sending message on Instagram: {m.group(1)[:50]}", f"instagram_dm_send||{m.group(1)}")
        # "send instagram message/dm" (no explicit "on")
        m = re.search(r"(?:send|message|dm)\s+(?:a\s+)?(?:message|dm)\s+(?:on\s+)?instagram", msg, re.IGNORECASE)
        if m:
            return ("Sending Instagram DM to first contact", "instagram_dm_send||")
        # "open instagram and send someone a message"
        m = re.search(r"(?:open|launch)\s+instagram\s+and\s+(?:send|message|dm)", msg, re.IGNORECASE)
        if m:
            return ("Opening Instagram and sending DM to first contact", "instagram_dm_send||")
        # "read instagram inbox" / "check instagram messages"
        m = re.search(r"(?:read|check|open|show)\s+(?:my\s+)?instagram\s+(?:inbox|dm|direct|messages)", msg, re.IGNORECASE)
        if m:
            return ("Reading Instagram inbox", "instagram_read_inbox")
        return None

    def _check_navigate_within_site(self, msg: str, context: Optional[dict] = None) -> Optional[Tuple[str, str]]:
        """Detect navigation within an already-open site (e.g. 'go to inbox' when Instagram is open)."""
        context = context or {"opened": ""}
        prev = context.get("opened", "").lower()

        # Instagram navigation
        if "instagram" in prev:
            m = re.search(r"(?:go to|open|navigate to)\s+(?:the\s+)?(?:direct\s+)?(?:inbox|messages?|dm)\b", msg, re.IGNORECASE)
            if m:
                return ("Navigating to Instagram inbox", 'start "" "https://www.instagram.com/direct/inbox"')
            m = re.search(r"(?:go to|open)\s+(?:my\s+)?profile", msg, re.IGNORECASE)
            if m:
                return ("Navigating to Instagram profile", 'start "" "https://www.instagram.com/accounts/access_tool/"')

        # Facebook/Messenger navigation
        if "messenger" in prev or "facebook" in prev:
            m = re.search(r"(?:go to|open)\s+(?:the\s+)?(?:inbox|messages?)", msg, re.IGNORECASE)
            if m:
                return ("Navigating to Messenger", 'start "" "https://www.messenger.com"')

        # YouTube navigation
        if "youtube" in prev:
            m = re.search(r"(?:go to|open)\s+(?:my\s+)?(?:subscriptions?|subs)", msg, re.IGNORECASE)
            if m:
                return ("Navigating to YouTube subscriptions", 'start "" "https://www.youtube.com/feed/subscriptions"')

        # Twitter/X navigation
        if any(p in prev for p in ["twitter", "x.com"]):
            m = re.search(r"(?:go to|open)\s+(?:my\s+)?(?:timeline|feed|home)", msg, re.IGNORECASE)
            if m:
                return ("Navigating to Twitter timeline", 'start "" "https://twitter.com/home"')

        # Generic "go to" with a known site section — only if a site is already open
        if prev.strip():
            m = re.search(r"(?:go to|open|navigate to)\s+(?:the\s+)?(\w+)", msg, re.IGNORECASE)
            if m:
                section = m.group(1).lower()
                # Extract the open site name from context
                for site_name in self.SITE_MAP:
                    if site_name in prev:
                        base_url = self.SITE_MAP[site_name].rstrip("/")
                        if section in ("home", "index", "main"):
                            return (f"Navigating to {site_name} home", f'start "" "{base_url}"')
                        # Try common URL patterns for sections
                        return (f"Navigating to {section} on {site_name}", f'start "" "{base_url}/{section}"')
        return None

    def _check_desktop_interaction(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect desktop mouse/keyboard/window/clipboard/screenshot commands."""
        # ---- Mouse ----
        # "move mouse to 500 300" / "move cursor to 500 300"
        m = re.search(r"(?:move|set|position)\s+(?:the\s+)?(?:mouse|cursor)\s+(?:to|at)\s+(\d+)\s*[, ]\s*(\d+)", msg, re.IGNORECASE)
        if m:
            x, y = m.group(1), m.group(2)
            return (f"Moving mouse to ({x}, {y})", f"desktop_mouse_move|{x}|{y}")

        # "click at 500 300" / "click on coordinates 500 300"
        m = re.search(r"(?:click|tap)\s+(?:at|on)\s+(\d+)\s*[, ]\s*(\d+)", msg, re.IGNORECASE)
        if m:
            x, y = m.group(1), m.group(2)
            return (f"Clicking at ({x}, {y})", f"desktop_click|{x}|{y}")

        # "double click at 500 300" / "double tap 500 300"
        m = re.search(r"(?:double\s*click|double\s*tap)\s+(?:at\s+)?(\d+)\s*[, ]\s*(\d+)", msg, re.IGNORECASE)
        if m:
            x, y = m.group(1), m.group(2)
            return (f"Double-clicking at ({x}, {y})", f"desktop_double_click|{x}|{y}")

        # "right click at 500 300"
        m = re.search(r"(?:right\s*click)\s+(?:at\s+)?(\d+)\s*[, ]\s*(\d+)", msg, re.IGNORECASE)
        if m:
            x, y = m.group(1), m.group(2)
            return (f"Right-clicking at ({x}, {y})", f"desktop_right_click|{x}|{y}")

        # "scroll down 3" / "scroll up 5"
        m = re.search(r"scroll\s+(down|up)\s*(\d+)?", msg, re.IGNORECASE)
        if m:
            direction = -1 if m.group(1) == "down" else 1
            clicks = int(m.group(2)) * direction if m.group(2) else (-3 if direction == -1 else 3)
            return (f"Scrolling {'down' if direction < 0 else 'up'}", f"desktop_scroll|{clicks}")

        # ---- Keyboard ----
        # "type 'hello world'" / "type hello world" / "write 'hello'"
        m = re.search(r"(?:type|write|input|enter)\s+[\"'](.+?)[\"']", msg, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            return (f"Typing '{text[:50]}'", f"desktop_type|{text}")

        # "press ctrl+c" / "press control c" / "press ctrl shift esc"
        m = re.search(r"(?:press|hit|send)\s+((?:\w+\+)*\w+)", msg, re.IGNORECASE)
        if m:
            combo = m.group(1).strip()
            # Check if it's a single key (enter, tab, etc.) vs a combo (ctrl+c)
            single_keys = {"enter", "tab", "escape", "esc", "space", "backspace",
                          "delete", "home", "end", "pageup", "pagedown",
                          "up", "down", "left", "right",
                          "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12"}
            if combo.lower() in single_keys:
                key_map = {"esc": "escape"}
                key = key_map.get(combo.lower(), combo.lower())
                return (f"Pressing '{key}'", f"desktop_press|{key}")
            else:
                # Keyboard shortcut — split on "+"
                keys = [k.strip().lower() for k in re.split(r'[+ ]', combo) if k.strip()]
                # Normalize
                key_map = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift",
                          "alt": "alt", "win": "win", "windows": "win",
                          "delete": "delete", "del": "delete",
                          "escape": "escape", "esc": "escape",
                          "tab": "tab", "enter": "enter", "space": "space",
                          "backspace": "backspace", "home": "home", "end": "end",
                          "pageup": "pageup", "pagedown": "pagedown",
                          "up": "up", "down": "down", "left": "left", "right": "right"}
                normalized = [key_map.get(k, k) for k in keys]
                return (f"Pressing {'+'.join(normalized)}", f"desktop_hotkey|{'|'.join(normalized)}")

        # ---- Screenshot ----
        if re.search(r"(?:take|capture|grab)\s+(?:a\s+)?(?:screenshot|screen\s*shot|screen\s*capture|pic(?:ture)?)", msg, re.IGNORECASE):
            return ("Taking screenshot", "desktop_screenshot")

        # ---- Windows ----
        # "focus Notepad" / "focus on Notepad" / "bring Notepad to front"
        m = re.search(r"(?:focus|bring\s+to\s+front|activate|switch\s+to)\s+(?:on\s+)?(.+?)$", msg, re.IGNORECASE)
        if m:
            title = m.group(1).strip().rstrip(".")
            if title and title not in ("window", "front"):
                return (f"Focusing '{title}'", f"desktop_focus|{title}")

        # "list windows" / "open windows" / "what windows are open"
        if re.search(r"(?:list|show|what)\s+(?:open\s+)?(?:windows?\s+)?(?:are\s+)?(?:open|visible|active)?", msg, re.IGNORECASE):
            if any(w in msg for w in ["window", "windows", "open window", "open windows"]):
                return ("Listing open windows", "desktop_list_windows")

        # "what is the active window" / "active window"
        if re.search(r"(?:active|current|foreground)\s+(?:window|app)", msg, re.IGNORECASE):
            return ("Getting active window info", "desktop_active_window")

        # "minimize Notepad" / "minimize window Notepad"
        m = re.search(r"minimize\s+(?:window\s+)?(.+?)$", msg, re.IGNORECASE)
        if m:
            title = m.group(1).strip().rstrip(".")
            return (f"Minimizing '{title}'", f"desktop_minimize_window|{title}")

        # "maximize Notepad"
        m = re.search(r"maximize\s+(?:window\s+)?(.+?)$", msg, re.IGNORECASE)
        if m:
            title = m.group(1).strip().rstrip(".")
            return (f"Maximizing '{title}'", f"desktop_maximize_window|{title}")

        # "close Notepad"
        m = re.search(r"close\s+(?:the\s+)?(?:window\s+)?(.+?)$", msg, re.IGNORECASE)
        if m:
            title = m.group(1).strip().rstrip(".")
            if title not in ("window", "app"):
                return (f"Closing '{title}'", f"desktop_close_window|{title}")

        # ---- Clipboard ----
        if re.search(r"(?:read|get|what(?:'s| is))\s+(?:my\s+)?(?:clipboard|clip\s*board)", msg, re.IGNORECASE):
            return ("Reading clipboard", "desktop_read_clipboard")

        m = re.search(r"(?:copy|write|put|set)\s+[\"'](.+?)[\"']\s+(?:to|into|on)\s+(?:the\s+)?(?:clipboard|clip\s*board)", msg, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            return (f"Copying '{text[:50]}' to clipboard", f"desktop_write_clipboard|{text}")

        # ---- Info ----
        if re.search(r"(?:mouse|cursor)\s+(?:position|location|coords|coordinates|where)", msg, re.IGNORECASE):
            return ("Getting mouse position", "desktop_mouse_position")

        if re.search(r"(?:screen|display|resolution)\s+(?:size|resolution)", msg, re.IGNORECASE):
            return ("Getting screen size", "desktop_screen_size")

        return None

    def _check_browser_interaction(self, msg: str) -> Optional[Tuple[str, str]]:
        """Detect click/type/press commands for the persistent browser."""
        # Skip if message is about file creation/operation, not browser typing
        if re.search(
            r"^(?:create|make|write|generate|new)\s+(?:a\s+)?file\b",
            msg.strip(), re.IGNORECASE,
        ):
            return None

        # "click on X" / "click X"
        click_match = re.search(
            r"(?:click|tap|press|select)\s+(?:on\s+)?(?:the\s+)?(?:button\s+|link\s+|element\s+)?(?:called\s+|labeled\s+|named\s+)?[\"']?(.+?)[\"']?\s*$",
            msg, re.IGNORECASE,
        )
        if click_match:
            target = click_match.group(1).strip().rstrip(".")
            return (f"Clicking '{target}' on page", f"browser_click|{target}")

        # "type X" / "type X in the message box" / "type X into the input"
        type_match = re.search(
            r"(?:type|enter|input|write)\s+[\"']?(.+?)[\"']?(?:\s+(?:in|into|on)\s+(?:the\s+)?(?:input|field|box|textarea|text\s+box|message\s+box|chat\s+input|search\s+bar))?\s*$",
            msg, re.IGNORECASE,
        )
        if type_match:
            text = type_match.group(1).strip().rstrip(".")
            return (f"Typing '{text[:50]}' on page", f"browser_type|{text}")

        # "press Enter" / "press Tab" / "press Escape"
        press_match = re.search(
            r"(?:press|hit|send)\s+(?:the\s+)?(Enter|Tab|Escape|Esc|Space|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|Backspace|Delete|Home|End|PageUp|PageDown|F\d+)\s*(?:key)?$",
            msg, re.IGNORECASE,
        )
        if press_match:
            key = press_match.group(1).strip()
            # Normalize common names
            key_map = {"Esc": "Escape", "Space": " "}
            key = key_map.get(key, key)
            return (f"Pressing '{key}'", f"browser_press|{key}")

        # "scroll down" / "scroll up"
        scroll_match = re.search(
            r"(?:scroll)\s+(?:down|up|to\s+(?:the\s+)?(?:bottom|top))",
            msg, re.IGNORECASE,
        )
        if scroll_match:
            direction = scroll_match.group(0).lower()
            if "up" in direction or "top" in direction:
                return ("Scrolling up", "browser_scroll|up")
            return ("Scrolling down", "browser_scroll|down")

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
