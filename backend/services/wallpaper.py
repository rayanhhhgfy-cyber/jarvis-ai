from __future__ import annotations

import ctypes
import random
import os
from pathlib import Path

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def set_wallpaper(image_path: str) -> str:
    path = os.path.abspath(image_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image not found: {path}")
    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )
    if not result:
        raise RuntimeError(f"SystemParametersInfoW failed (error {ctypes.GetLastError()})")
    return f"Wallpaper set to: {path}"


def set_random_wallpaper() -> str:
    candidates = []
    for root in [
        os.environ.get("WINDIR", "C:\\Windows") + "\\Web\\Wallpaper",
    ]:
        if os.path.isdir(root):
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
                candidates.extend(Path(root).rglob(ext))
    if not candidates:
        raise FileNotFoundError("No wallpaper images found in Windows\\Web\\Wallpaper")
    chosen = str(random.choice(candidates))
    return set_wallpaper(chosen)
