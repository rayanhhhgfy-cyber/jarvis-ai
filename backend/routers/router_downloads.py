# ====================================================================
# JARVIS OMEGA — Release Downloads Router
# ====================================================================
"""Serve desktop/Android release artifacts from the releases/ directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from shared.logger import get_logger

log = get_logger("router_downloads")

router = APIRouter(prefix="/api/downloads", tags=["Downloads"])

# Project root: backend/routers -> backend -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RELEASES_DIR = _PROJECT_ROOT / "releases"

# Allowed filenames (prevents path traversal)
_CATALOG: Dict[str, Dict[str, str]] = {
    "jarvis-desktop-windows.zip": {
        "title": "Desktop Client (Windows)",
        "description": "Python daemon + launcher — extract and run Start-Jarvis-Desktop.bat",
        "platform": "windows",
        "content_type": "application/zip",
    },
    "jarvis-android-build-guide.txt": {
        "title": "Android APK — Build Guide",
        "description": "Instructions to build the APK in Android Studio",
        "platform": "android",
        "content_type": "text/plain",
    },
    "jarvis-android.apk": {
        "title": "Android App (APK)",
        "description": "Install on your phone (sideload)",
        "platform": "android",
        "content_type": "application/vnd.android.package-archive",
    },
}


def _catalog_names() -> List[str]:
    """All known release filenames (APK only listed if present on disk)."""
    names = list(_CATALOG.keys())
    apk = _releases_path() / "jarvis-android.apk"
    if not apk.is_file() and "jarvis-android.apk" in names:
        return [n for n in names if n != "jarvis-android.apk"]
    return names


def _releases_path() -> Path:
    _RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    return _RELEASES_DIR


def _file_info(name: str) -> Dict[str, Any]:
    path = _releases_path() / name
    meta = _CATALOG.get(name, {})
    exists = path.is_file()
    return {
        "id": name,
        "filename": name,
        "title": meta.get("title", name),
        "description": meta.get("description", ""),
        "platform": meta.get("platform", "unknown"),
        "available": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "download_url": f"/api/downloads/{name}" if exists else None,
    }


@router.get("")
async def list_downloads() -> Dict[str, Any]:
    """List release artifacts and whether each file is on disk."""
    items = [_file_info(name) for name in _catalog_names()]
    return {
        "releases_dir": str(_releases_path()),
        "items": items,
        "available_count": sum(1 for i in items if i["available"]),
    }


@router.get("/{filename}")
async def download_file(filename: str):
    """Download a release file by name."""
    safe_name = os.path.basename(filename)
    if safe_name not in _CATALOG:
        raise HTTPException(status_code=404, detail="Unknown download")

    path = _releases_path() / safe_name
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"File '{safe_name}' is not built yet. Run: "
                f"powershell -File scripts/package_desktop_client.ps1"
            ),
        )

    meta = _CATALOG[safe_name]
    log.info("download_served", filename=safe_name, size=path.stat().st_size)
    return FileResponse(
        path=path,
        filename=safe_name,
        media_type=meta.get("content_type", "application/octet-stream"),
    )
