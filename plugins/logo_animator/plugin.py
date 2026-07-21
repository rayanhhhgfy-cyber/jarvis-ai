# Phase 18: Logo Animator (REAL)
from __future__ import annotations
import io, base64, math
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="logo.animate", description="Create an animated GIF from a static logo (fade + zoom effect).", parameters={"type":"object","properties":{"logo_path":{"type":"string"},"frames":{"type":"integer","default":10},"output_path":{"type":"string","default":""}},"required":["logo_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="logo_animator")
async def animate(logo_path: str, frames: int = 10, output_path: str = "") -> Dict[str, Any]:
    try:
        from PIL import Image
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    if not Path(logo_path).exists(): return {"ok": False, "error": "logo not found"}
    logo = Image.open(logo_path).convert("RGBA")
    w, h = logo.size
    anim_frames = []
    for i in range(frames):
        progress = i / max(1, frames - 1)
        # Fade in + slight zoom
        alpha = int(255 * min(1, progress * 2))
        scale = 0.8 + 0.2 * progress
        new_size = (int(w * scale), int(h * scale))
        frame = logo.resize(new_size)
        # Center on canvas
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        offset = ((w - new_size[0]) // 2, (h - new_size[1]) // 2)
        frame.putalpha(alpha)
        canvas.paste(frame, offset, frame)
        anim_frames.append(canvas.convert("RGB"))
    out = output_path or str(Path(logo_path).with_suffix(".gif"))
    anim_frames[0].save(out, save_all=True, append_images=anim_frames[1:], duration=100, loop=0, format="GIF")
    return {"ok": True, "gif_path": out, "frames": frames}
