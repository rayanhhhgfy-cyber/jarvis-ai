# Phase 18: AI Photo Editor (REAL)
from __future__ import annotations
import io, base64
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="photo.remove_bg", description="Remove background from an image (simple flood-fill approach).", parameters={"type":"object","properties":{"image_path":{"type":"string"},"tolerance":{"type":"integer","default":30}},"required":["image_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="ai_photo_editor")
async def remove_bg(image_path: str, tolerance: int = 30) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageChops
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    img = Image.open(image_path).convert("RGB")
    # Simple approach: assume top-left corner is background color
    bg = img.getpixel((0, 0))
    bg_img = Image.new("RGB", img.size, bg)
    diff = ImageChops.difference(img, bg_img)
    # Convert to grayscale + threshold
    gray = diff.convert("L")
    mask = gray.point(lambda x: 255 if x > tolerance else 0)
    result = img.convert("RGBA")
    result.putalpha(mask)
    out = image_path.rsplit(".", 1)[0] + "_nobg.png"
    result.save(out, "PNG")
    return {"ok": True, "output_path": out, "note": "Simple background removal. For production use rembg library."}

@tool(name="photo.enhance", description="Enhance image quality (contrast, sharpness, color).", parameters={"type":"object","properties":{"image_path":{"type":"string"},"contrast":{"type":"number","default":1.3},"sharpness":{"type":"number","default":1.5},"color":{"type":"number","default":1.2}},"required":["image_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="ai_photo_editor")
async def enhance(image_path: str, contrast: float = 1.3, sharpness: float = 1.5, color: float = 1.2) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageEnhance
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    img = Image.open(image_path)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)
    img = ImageEnhance.Color(img).enhance(color)
    out = image_path.rsplit(".", 1)[0] + "_enhanced.jpg"
    img.save(out, "JPEG", quality=95)
    return {"ok": True, "output_path": out}
