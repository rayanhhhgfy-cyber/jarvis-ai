"""
File download service — downloads files from URLs and saves them to local storage.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from shared.logger import get_logger

log = get_logger("file_download_service")

_DOWNLOAD_DIR = Path.home() / "Downloads"


class FileDownloadService:

    async def download(
        self,
        url: str,
        save_dir: Optional[str] = None,
        filename: Optional[str] = None,
        max_size_mb: int = 500,
    ) -> Dict[str, Any]:
        """
        Download a file from a URL and save it to disk.

        Args:
            url: The URL to download from
            save_dir: Directory to save the file (default: Downloads)
            filename: Custom filename (default: inferred from URL)
            max_size_mb: Maximum file size in MB

        Returns:
            {success, filepath, filename, size_bytes, mime_type, error}
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        save_path = Path(save_dir or _DOWNLOAD_DIR)
        save_path.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = self._infer_filename(url)

        dest = save_path / filename
        max_bytes = max_size_mb * 1024 * 1024

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
                async with client.stream("GET", url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }) as resp:
                    resp.raise_for_status()

                    content_length = resp.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        return {
                            "success": False,
                            "error": f"File too large: {int(content_length) // 1024 // 1024}MB > {max_size_mb}MB limit",
                        }

                    mime_type = resp.headers.get("content-type", "application/octet-stream")
                    ext = self._guess_extension(mime_type, filename)

                    if not filename.endswith(ext):
                        filename += ext
                        dest = save_path / filename

                    downloaded = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                dest.unlink(missing_ok=True)
                                return {
                                    "success": False,
                                    "error": f"Download exceeded {max_size_mb}MB limit",
                                }
                            f.write(chunk)

            log.info("file_downloaded", url=url, path=str(dest), size=downloaded, mime=mime_type)
            return {
                "success": True,
                "filepath": str(dest),
                "filename": filename,
                "size_bytes": downloaded,
                "mime_type": mime_type,
            }

        except httpx.HTTPStatusError as e:
            log.error("download_http_error", url=url, status=e.response.status_code)
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
        except httpx.TimeoutException:
            log.error("download_timeout", url=url)
            return {"success": False, "error": "Download timed out"}
        except Exception as e:
            log.error("download_failed", url=url, error=str(e))
            return {"success": False, "error": str(e)}

    def _infer_filename(self, url: str) -> str:
        """Extract a filename from a URL."""
        path = urlparse(url).path
        name = Path(path).name
        if not name or name == "/":
            return "download"
        # Remove query params
        name = name.split("?")[0]
        return name

    def _guess_extension(self, mime_type: str, filename: str) -> str:
        """Guess file extension from MIME type if filename doesn't already have one."""
        if "." in filename:
            return ""
        ext = mimetypes.guess_extension(mime_type.split(";")[0].strip())
        return ext or ".bin"


file_download_service = FileDownloadService()
