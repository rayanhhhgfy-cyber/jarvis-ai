from __future__ import annotations

import hashlib
from typing import Optional, Callable


class DynamicSampler:
    """
    Compares screenshot hashes to avoid sending identical frames to the
    vision model, reducing token costs by up to 90% on static screens.
    """

    def __init__(self) -> None:
        self._last_hash: Optional[str] = None
        self._skip_count: int = 0
        self._total_count: int = 0
        self._change_threshold: float = 0.05

    def should_analyze(self, image_bytes: bytes) -> bool:
        self._total_count += 1
        h = hashlib.sha256(image_bytes).hexdigest()
        if h == self._last_hash:
            self._skip_count += 1
            return False
        self._last_hash = h
        return True

    def reset(self) -> None:
        self._last_hash = None

    @property
    def stats(self) -> dict:
        return {
            "total_frames": self._total_count,
            "skipped_frames": self._skip_count,
            "savings_pct": round(
                (self._skip_count / max(self._total_count, 1)) * 100, 1
            ),
        }


dynamic_sampler = DynamicSampler()
