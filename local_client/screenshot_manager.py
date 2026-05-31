# ====================================================================
# JARVIS OMEGA — Screenshot Manager
# ====================================================================
"""
Captures high-resolution screen shots across multi-monitor setups.
Supports image compression, crop regions, and raw bytes generation.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from shared.logger import get_logger

log = get_logger("screenshot_manager")

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


class ScreenshotManager:
    """
    Manages screen frame captures. Uses mss for cross-platform fast grabbing,
    falling back to PIL drawn placeholder frames if display is offline.
    """

    def __init__(self, output_dir: str = "./storage/screenshots") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, monitor_index: int = 1, quality: int = 75) -> bytes:
        """
        Captures the screen and returns compressed JPEG image bytes.
        """
        if not MSS_AVAILABLE:
            log.warning("mss_not_available_generating_placeholder")
            return self._generate_placeholder_bytes("MSS Library Missing")

        try:
            with mss.mss() as sct:
                # Validate monitor index
                monitors = sct.monitors
                if monitor_index < 0 or monitor_index >= len(monitors):
                    monitor_index = 1  # Fallback to primary

                monitor = monitors[monitor_index]
                sct_img = sct.grab(monitor)
                
                # Convert raw pixels to PIL Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                # Compress to JPEG
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=quality)
                
                log.info(
                    "screenshot_captured",
                    monitor=monitor_index,
                    size=f"{img.width}x{img.height}",
                    bytes_len=buffer.tell(),
                )
                return buffer.getvalue()

        except Exception as e:
            log.error("screen_capture_failed", error=str(e))
            return self._generate_placeholder_bytes(f"Capture Error: {str(e)}")

    def save_to_disk(self, filename: str = "screenshot.jpg", monitor_index: int = 1) -> str:
        """Captures screen and saves file to the local storage screenshots folder."""
        data = self.capture(monitor_index)
        out_path = self.output_dir / filename
        out_path.write_bytes(data)
        log.info("screenshot_saved_to_disk", path=str(out_path))
        return str(out_path.absolute().as_posix())

    def _generate_placeholder_bytes(self, message: str) -> bytes:
        """Generates a dummy gray JPEG image displaying a message."""
        img = Image.new("RGB", (800, 600), color=(50, 50, 50))
        d = ImageDraw.Draw(img)
        d.text((50, 280), f"JARVIS OMEGA SCREENSHOT FALLBACK\n{message}", fill=(200, 200, 200))
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=60)
        return buffer.getvalue()


# Global screenshot manager instance
screenshot_manager = ScreenshotManager()
