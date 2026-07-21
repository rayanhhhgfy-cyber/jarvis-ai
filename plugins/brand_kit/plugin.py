# JARVIS OMEGA - Brand Kit Generator (Phase 16)
from __future__ import annotations
import io, base64, json, math, random
from pathlib import Path
from typing import Any, Dict, List
from backend.tools import tool, RiskTier

_PALETTES = {"tech":["#4F46E5","#06B6D4","#1E1B4B","#F1F5F9"],"food":["#DC2626","#F59E0B","#166534","#FFFBEB"],"health":["#059669","#0EA5E9","#064E3B","#F0FDF4"],"luxury":["#7C3AED","#1E293B","#FBBF24","#FAFAFA"],"creative":["#EC4899","#8B5CF6","#F97316","#FFF7ED"]}

@tool(name="brand.logo_generate", description="Generate a text-based logo PNG from business name + niche. Uses Pillow.", parameters={"type":"object","properties":{"business_name":{"type":"string"},"niche":{"type":"string","default":"general"},"color_scheme":{"type":"string","default":"tech","enum":["tech","food","health","luxury","creative"]},"size":{"type":"integer","default":400}},"required":["business_name"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="brand_kit")
async def logo_generate(business_name: str, niche: str = "general", color_scheme: str = "tech", size: int = 400) -> Dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    colors = _PALETTES.get(color_scheme, _PALETTES["tech"])
    bg, accent, dark, light = colors[0], colors[1], colors[2], colors[3]
    img = Image.new("RGB", (size, size), dark)
    draw = ImageDraw.Draw(img)
    # Draw accent circle
    r = size // 3
    cx, cy = size//2, size//2 - 20
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=accent)
    # Business initials
    initials = "".join([w[0].upper() for w in business_name.split()[:2]]) or business_name[:2].upper()
    try: font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size//3)
    except: font = ImageFont.load_default()
    # Center text
    bbox = draw.textbbox((0,0), initials, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text((cx-tw//2, cy-th//2-5), initials, fill=light, font=font)
    # Business name at bottom
    try: small_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size//10)
    except: small_font = font
    bbox2 = draw.textbbox((0,0), business_name, font=small_font)
    tw2 = bbox2[2]-bbox2[0]
    draw.text((size//2-tw2//2, size-50), business_name[:25], fill=accent, font=small_font)
    # Save
    out = Path("./storage/brand_kit"); out.mkdir(parents=True, exist_ok=True)
    path = out / f"logo_{business_name.lower().replace(' ','_')}.png"
    img.save(str(path), "PNG")
    buf = io.BytesIO(); img.save(buf, "PNG"); b64 = base64.b64encode(buf.getvalue()).decode()
    return {"ok": True, "logo_path": str(path), "logo_base64": b64, "colors": colors}

@tool(name="brand.color_palette", description="Get a recommended color palette for a niche.", parameters={"type":"object","properties":{"niche":{"type":"string"}},"required":["niche"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="brand_kit")
async def color_palette(niche: str) -> Dict[str, Any]:
    n = niche.lower()
    scheme = "food" if any(w in n for w in ["food","restaurant","coffee","bakery"]) else "health" if any(w in n for w in ["health","medical","fitness"]) else "luxury" if any(w in n for w in ["jewelry","watch","premium","real estate"]) else "creative" if any(w in n for w in ["art","design","media"]) else "tech"
    colors = _PALETTES[scheme]
    return {"ok": True, "scheme": scheme, "primary": colors[0], "secondary": colors[1], "dark": colors[2], "light": colors[3], "css": f":root{{--primary:{colors[0]};--secondary:{colors[1]};--dark:{colors[2]};--light:{colors[3]}}}"}

@tool(name="brand.font_pairing", description="Recommend Arabic + Latin font pairings for a brand.", parameters={"type":"object","properties":{"style":{"type":"string","default":"modern","enum":["modern","classic","playful","corporate"]}}}, risk_tier=RiskTier.TIER_0_OBSERVE, category="brand_kit")
async def font_pairing(style: str = "modern") -> Dict[str, Any]:
    pairs = {"modern":{"ar":"Tajawal","en":"Inter","css_ar":"@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap')","css_en":"@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap')"},
             "classic":{"ar":"Amiri","en":"Playfair Display","css_ar":"@import url('https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&display=swap')","css_en":"@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&display=swap')"},
             "playful":{"ar":"Cairo","en":"Poppins","css_ar":"@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap')","css_en":"@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap')"},
             "corporate":{"ar":"IBM Plex Sans Arabic","en":"IBM Plex Sans","css_ar":"@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;700&display=swap')","css_en":"@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;700&display=swap')"}}
    p = pairs.get(style, pairs["modern"])
    return {"ok": True, "style": style, **p}

@tool(name="brand.social_kit", description="Generate profile picture + cover photo sized for each social platform.", parameters={"type":"object","properties":{"logo_path":{"type":"string"},"business_name":{"type":"string"}},"required":["logo_path"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="brand_kit")
async def social_kit(logo_path: str, business_name: str = "") -> Dict[str, Any]:
    try: from PIL import Image
    except ImportError: return {"ok": False, "error": "Pillow not installed"}
    if not Path(logo_path).exists(): return {"ok": False, "error": "logo not found"}
    logo = Image.open(logo_path)
    sizes = {"instagram_pfp":(320,320),"facebook_cover":(1640,856),"twitter_header":(1500,500),"linkedin_banner":(1584,396)}
    out_dir = Path("./storage/brand_kit/social"); out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, (w,h) in sizes.items():
        img = logo.resize((min(w,logo.width),min(h,logo.height)))
        bg = Image.new("RGB",(w,h),(30,30,30))
        bg.paste(img,((w-img.width)//2,(h-img.height)//2))
        p = out_dir / f"{name}.png"; bg.save(str(p),"PNG"); paths[name]=str(p)
    return {"ok": True, "sizes": paths}

@tool(name="brand.guideline_pdf", description="Generate a brand guideline HTML document (logo + colors + fonts + usage).", parameters={"type":"object","properties":{"business_name":{"type":"string"},"colors":{"type":"object","default":{}},"fonts":{"type":"object","default":{}}}}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="brand_kit")
async def guideline_pdf(business_name: str, colors: dict = {}, fonts: dict = {}) -> Dict[str, Any]:
    from datetime import datetime
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Brand Guidelines — {business_name}</title>
<style>body{{font-family:Tajawal,Arial;max-width:800px;margin:auto;padding:40px}}
h1{{color:{colors.get('primary','#4F46E5')}}} .swatch{{display:inline-block;width:80px;height:80px;border-radius:8px;margin:10px}}</style>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap"></head>
<body><h1>{business_name}</h1><p>Brand Guidelines — {datetime.utcnow().strftime('%Y')}</p>
<h2>Colors</h2>{''.join(f'<div class="swatch" style="background:{v}" title="{k}={v}"></div>' for k,v in colors.items()) if colors else '<p>See brand.color_palette</p>'}
<h2>Fonts</h2><p>Arabic: {fonts.get('ar','Tajawal')} | English: {fonts.get('en','Inter')}</p>
<h2>Logo Usage</h2><p>Minimum size: 100px. Clear space: equal to logo height. Don't stretch or recolor.</p>
<p style="color:#999;font-size:12px">Generated by JARVIS OMEGA</p></body></html>"""
    out = Path("./storage/brand_kit"); out.mkdir(parents=True, exist_ok=True)
    path = out / f"guidelines_{business_name.lower().replace(' ','_')}.html"
    path.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(path)}

PLUGIN_NAME = "brand_kit"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Brand identity: logo, colors, fonts, social kit, guidelines."
