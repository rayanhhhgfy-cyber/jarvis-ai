# ====================================================================
# JARVIS OMEGA — Free Media Plugin (Pollinations + Pillow + QR)
# ====================================================================
"""
Phase 10 plugin: image generation + image editing + QR codes — all free,
no API keys required.

  * ``media.image_pollinations`` — free FLUX/SDXL via pollinations.ai
    (one HTTP GET per image).
  * ``media.image_crop / resize / filter / annotate`` — Pillow (already
    in requirements.txt).
  * ``media.qr_make / qr_read`` — generate + scan QR codes.

All tools degrade gracefully if their backing library is missing.
"""

from __future__ import annotations

import base64
import io
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Image generation (Pollinations — free, no key)
# --------------------------------------------------------------------

@tool(
    name="media.image_pollinations",
    description="Generate an image from a text prompt using Pollinations.ai (free FLUX model, no API key). Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What to depict."},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "seed": {"type": "integer", "default": 0, "description": "0 = random each call."},
            "model": {"type": "string", "default": "flux", "enum": ["flux", "flux-realism", "flux-anime", "flux-3d", "turbo"]},
            "nologo": {"type": "boolean", "default": True},
        },
        "required": ["prompt"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_image_pollinations(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    seed: int = 0,
    model: str = "flux",
    nologo: bool = True,
) -> Dict[str, Any]:
    import httpx
    params = {
        "width": str(width),
        "height": str(height),
        "model": model,
        "nologo": "true" if nologo else "false",
    }
    if seed:
        params["seed"] = str(seed)
    encoded_prompt = urllib.parse.quote(prompt, safe="")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?{urllib.parse.urlencode(params)}"
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
        img_bytes = resp.content
        return {
            "ok": True,
            "image_base64": base64.b64encode(img_bytes).decode("ascii"),
            "bytes": len(img_bytes),
            "format": "png",
            "source_url": url,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Image editing (Pillow — already in requirements.txt)
# --------------------------------------------------------------------

def _load_pillow():
    try:
        from PIL import Image, ImageFilter, ImageDraw, ImageFont
        return Image, ImageFilter, ImageDraw, ImageFont
    except ImportError as e:
        raise RuntimeError("Pillow is not installed") from e


def _decode_image(b64_or_path: str):
    """Accept either a base64-encoded image OR a file path. Returns a PIL Image."""
    Image, *_ = _load_pillow()
    # If the string is a path to an existing file, open it directly.
    from pathlib import Path
    try:
        if "\n" not in b64_or_path and len(b64_or_path) < 4096 and Path(b64_or_path).is_file():
            return Image.open(b64_or_path)
    except OSError:
        pass
    # Strip optional data URL prefix then b64-decode.
    raw = b64_or_path
    if "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    try:
        decoded = base64.b64decode(raw, validate=False)
        return Image.open(io.BytesIO(decoded))
    except Exception as e:
        raise ValueError(f"could not decode image (not a valid path or base64): {e}")


def _encode_image(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@tool(
    name="media.image_crop",
    description="Crop an image (base64 or file path). Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string", "description": "Base64-encoded image OR a local file path."},
            "left": {"type": "integer"}, "top": {"type": "integer"},
            "right": {"type": "integer"}, "bottom": {"type": "integer"},
        },
        "required": ["image", "left", "top", "right", "bottom"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_image_crop(image: str, left: int, top: int, right: int, bottom: int) -> Dict[str, Any]:
    try:
        img = _decode_image(image)
        cropped = img.crop((left, top, right, bottom))
        return {"ok": True, "image_base64": _encode_image(cropped), "format": "png"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="media.image_resize",
    description="Resize an image to specific dimensions. Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        "required": ["image", "width", "height"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_image_resize(image: str, width: int, height: int) -> Dict[str, Any]:
    try:
        img = _decode_image(image)
        resized = img.resize((width, height))
        return {"ok": True, "image_base64": _encode_image(resized), "format": "png"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="media.image_filter",
    description="Apply a Pillow filter to an image. Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string"},
            "filter": {"type": "string", "enum": ["blur", "sharpen", "grayscale", "edge_enhance", "contour", "emboss"]},
        },
        "required": ["image", "filter"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_image_filter(image: str, filter: str) -> Dict[str, Any]:
    try:
        Image, ImageFilter, *_ = _load_pillow()
        img = _decode_image(image)
        if filter == "blur":
            out = img.filter(ImageFilter.BLUR)
        elif filter == "sharpen":
            out = img.filter(ImageFilter.SHARPEN)
        elif filter == "grayscale":
            out = img.convert("L")
        elif filter == "edge_enhance":
            out = img.filter(ImageFilter.EDGE_ENHANCE)
        elif filter == "contour":
            out = img.filter(ImageFilter.CONTOUR)
        elif filter == "emboss":
            out = img.filter(ImageFilter.EMBOSS)
        else:
            return {"ok": False, "error": f"unknown filter: {filter}"}
        return {"ok": True, "image_base64": _encode_image(out), "format": "png"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="media.image_annotate",
    description="Draw text on an image at a specific position. Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string"},
            "text": {"type": "string"},
            "x": {"type": "integer", "default": 10},
            "y": {"type": "integer", "default": 10},
            "color": {"type": "string", "default": "red", "description": "Color name or hex like '#ff0000'."},
        },
        "required": ["image", "text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_image_annotate(image: str, text: str, x: int = 10, y: int = 10, color: str = "red") -> Dict[str, Any]:
    try:
        _, _, ImageDraw, ImageFont = _load_pillow()
        img = _decode_image(image).convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        draw.text((x, y), text, fill=color, font=font)
        return {"ok": True, "image_base64": _encode_image(img), "format": "png"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# QR codes
# --------------------------------------------------------------------

@tool(
    name="media.qr_make",
    description="Generate a QR code image from text. Returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "box_size": {"type": "integer", "default": 10},
            "border": {"type": "integer", "default": 4},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="media",
)
async def media_qr_make(text: str, box_size: int = 10, border: int = 4) -> Dict[str, Any]:
    try:
        import qrcode  # type: ignore
    except ImportError:
        return {"ok": False, "error": "qrcode library not installed — add `qrcode[pil]` to requirements.txt"}
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=box_size, border=border)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return {
            "ok": True,
            "image_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "format": "png",
            "source_text_length": len(text),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="media.qr_read",
    description="Decode QR codes from an image (base64 or file path). Returns a list of detected strings.",
    parameters={
        "type": "object",
        "properties": {
            "image": {"type": "string"},
        },
        "required": ["image"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="media",
)
async def media_qr_read(image: str) -> Dict[str, Any]:
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode  # type: ignore
    except ImportError:
        return {"ok": False, "error": "pyzbar not installed — add `pyzbar` to requirements.txt and the zbar system library"}
    try:
        img = _decode_image(image)
        decoded = pyzbar_decode(img)
        texts = [d.data.decode("utf-8", errors="replace") for d in decoded]
        return {"ok": True, "count": len(texts), "texts": texts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "media_free"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Free image generation (Pollinations), Pillow-based editing, and QR code tools."
