from __future__ import annotations

import os
import sys
from pathlib import Path
from shared.logger import get_logger

log = get_logger("startup_service")


def get_startup_folder() -> Path:
    """Gets the path to the user's Windows Startup folder."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"


def update_startup_status(enabled: bool) -> None:
    """Enables or disables startup-on-boot on Windows by creating a hidden VBS wrapper."""
    if sys.platform != "win32":
        log.warning("startup_not_supported_non_windows", platform=sys.platform)
        return

    workspace_root = Path(__file__).resolve().parent.parent.parent
    bat_path = workspace_root / "start_jarvis_all.bat"
    startup_dir = get_startup_folder()
    vbs_path = startup_dir / "jarvis_startup.vbs"

    if enabled:
        try:
            # Create start_jarvis_all.bat in root directory if not present,
            # or overwrite to make sure paths are correct.
            bat_content = (
                "@echo off\r\n"
                f'cd /d "{workspace_root}"\r\n'
                "echo ============================================\r\n"
                "echo   J.A.R.V.I.S. OMEGA — Server Startup Suite\r\n"
                "echo ============================================\r\n"
                "echo.\r\n"
                "echo Starting Backend (uvicorn on port 8000)...\r\n"
                'start "JARVIS Backend" cmd /c "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"\r\n'
                "timeout /t 3 /nobreak > nul\r\n"
                "echo Starting Frontend (npm run dev on port 3000)...\r\n"
                'start "JARVIS Frontend" cmd /c "cd frontend && npm run dev"\r\n'
                "timeout /t 5 /nobreak > nul\r\n"
                "echo Opening browser to http://localhost:3000...\r\n"
                "start http://localhost:3000\r\n"
                "echo.\r\n"
                "echo Both servers have been launched in separate windows.\r\n"
                "echo You can close this window now.\r\n"
            )
            bat_path.write_text(bat_content, encoding="utf-8")
            log.info("startup_bat_written", path=str(bat_path))
        except Exception as e:
            log.error("failed_to_write_startup_bat", error=str(e))
            return

        # Write the jarvis_startup.vbs file in the Startup directory
        try:
            startup_dir.mkdir(parents=True, exist_ok=True)
            vbs_content = (
                'Set WshShell = CreateObject("WScript.Shell")\r\n'
                f'WshShell.Run """{bat_path}""", 0, False\r\n'
            )
            vbs_path.write_text(vbs_content, encoding="utf-8")
            log.info("startup_vbs_written", path=str(vbs_path))
        except Exception as e:
            log.error("failed_to_write_vbs_shortcut", error=str(e))
    else:
        # Clean up files if disabled
        try:
            if vbs_path.exists():
                vbs_path.unlink()
                log.info("startup_vbs_removed", path=str(vbs_path))
        except Exception as e:
            log.error("failed_to_remove_vbs_shortcut", error=str(e))
