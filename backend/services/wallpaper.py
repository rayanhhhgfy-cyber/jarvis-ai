from __future__ import annotations

import ctypes
import os
import random
import re
import tempfile
import urllib.parse
from pathlib import Path

import httpx

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def _set_wallpaper_raw(path: str) -> bool:
    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )
    return bool(result)


def set_wallpaper(image_path: str) -> str:
    path = os.path.abspath(image_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image not found: {path}")
    if _set_wallpaper_raw(path):
        return f"Wallpaper set to: {path}"
    raise RuntimeError(f"Failed to set wallpaper (error {ctypes.GetLastError()})")


def set_random_wallpaper() -> str:
    candidates = []
    root = os.environ.get("WINDIR", "C:\\Windows") + "\\Web\\Wallpaper"
    if os.path.isdir(root):
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            candidates.extend(Path(root).rglob(ext))
    if not candidates:
        raise FileNotFoundError("No wallpaper images found in Windows\\Web\\Wallpaper")
    chosen = str(random.choice(candidates))
    return set_wallpaper(chosen)


def _wikipedia_image(query: str) -> str:
    headers = {"User-Agent": "JARVIS-OMEGA/1.0 (wallpaper downloader)"}

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 3,
        }
        resp = client.get(search_url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("search", [])
        if not pages:
            raise FileNotFoundError(f"No Wikipedia results for: {query}")

        title = pages[0]["title"]

        img_params = {
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 1920,
        }
        resp = client.get(search_url, params=img_params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        pages_data = data.get("query", {}).get("pages", {})
        for pid, info in pages_data.items():
            thumb = info.get("thumbnail", {})
            src = thumb.get("source", "")
            if src:
                return src

        raise FileNotFoundError(f"No thumbnail found for Wikipedia page: {title}")


def search_and_set_wallpaper_sync(query: str) -> str:
    image_url = _wikipedia_image(query)

    headers = {"User-Agent": "JARVIS-OMEGA/1.0 (image download)"}

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        img_resp = client.get(image_url, headers=headers)
        if img_resp.status_code != 200:
            raise RuntimeError(f"Image download failed (HTTP {img_resp.status_code})")

        ext = _guess_extension(image_url, img_resp.headers.get("content-type", ""))
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix="jarvis_wp_")
        tmp_path = tmp.name
        tmp.write(img_resp.content)
        tmp.close()

    result = set_wallpaper(tmp_path)
    return f'{result} (downloaded from Wikipedia)'


async def search_and_set_wallpaper(query: str) -> str:
    return search_and_set_wallpaper_sync(query)


def _guess_extension(url: str, content_type: str) -> str:
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    if content_type in ext_map:
        return ext_map[content_type]
    _, ext = os.path.splitext(urllib.parse.urlparse(url).path)
    return ext if ext else ".jpg"
