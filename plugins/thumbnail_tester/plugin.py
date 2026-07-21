# Phase 18: Thumbnail A/B Tester (REAL)
from __future__ import annotations
import io, base64
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="thumb.generate_variants", description="Generate 3 thumbnail variants with different text colors/layouts.", parameters={"type":"object","properties":{"title":{"type":"string"},"bg_image_path":{"type":"string"}},"required":["title"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="thumbnail_tester")
async def generate_variants(title: str, bg_image_path: str = "") -> Dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    colors = [("yellow","red"),("white","blue"),("green","black")]
    variants = []
    for i, (text_color, bg_color) in enumerate(colors):
        img = Image.new("RGB", (1280, 720), bg_color)
        draw = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 80)
        except: font = ImageFont.load_default()
        # Wrap text
        words = title.split()
        lines = []; current = ""
        for w in words:
            if len(current + w) < 20: current += " " + w
            else: lines.append(current.strip()); current = w
        if current: lines.append(current)
        y = 360 - len(lines) * 45
        for line in lines[:3]:
            draw.text((100, y), line, fill=text_color, font=font, stroke_width=3, stroke_fill="black")
            y += 90
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=90)
        variants.append({"variant": i+1, "text_color": text_color, "bg_color": bg_color, "image_base64": base64.b64encode(buf.getvalue()).decode()})
    return {"ok": True, "variants": variants, "title": title}
