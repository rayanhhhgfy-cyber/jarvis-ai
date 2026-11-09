#!/usr/bin/env python3
# ====================================================================
# J.A.R.V.I.S. OMEGA — PWA icon generator (standalone)
# ====================================================================
"""
Renders the three PWA icons deterministically with PIL into
``frontend/pwa/icons/`` — the same mark as the backend runtime
generator (``backend/main.py:_generate_pwa_icon``): dark gradient,
cyan ring + purple arc, bold "J" in the cyan/purple theme.

Why a script and not committed PNGs: the GitHub push path is UTF-8
only, so binary assets cannot be pushed through it. Instead:
  * Render: the backend generates the icons on first request
    (``_generate_pwa_icon``) and caches them on disk — fallback.
  * Vercel (static): the build runs this script
    (``frontend/vercel.json`` buildCommand) so the icons exist as
    real static files at deploy time.

Run:  python3 frontend/pwa/generate_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ICON_SIZES = {"icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180}


def render_icon(filename: str, path: Path) -> bool:
    """Render one icon. Returns True when the file now exists."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow is required (pip install Pillow)", file=sys.stderr)
        return False
    size = ICON_SIZES[filename]
    img = Image.new("RGB", (size, size), (10, 10, 26))
    draw = ImageDraw.Draw(img)
    # Vertical dark gradient (deep navy -> purple-black).
    for y in range(size):
        t = y / max(size - 1, 1)
        draw.line([(0, y), (size, y)], fill=(
            int(10 + (26 - 10) * t),
            int(10 + (16 - 10) * t),
            int(26 + (48 - 26) * t),
        ))
    pad = size // 12
    # Cyan ring.
    draw.ellipse([pad, pad, size - pad, size - pad], outline=(0, 212, 255), width=max(2, size // 48))
    # Purple arc (upper right).
    draw.arc([pad, pad, size - pad, size - pad], start=-80, end=40, fill=(168, 85, 247), width=max(3, size // 32))
    # Bold "J".
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            size=int(size * 0.55),
        )
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), "J", fill=(0, 212, 255), font=font, anchor="mm")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format="PNG")
    except OSError as err:
        print(f"failed to save {filename}: {err}", file=sys.stderr)
        return False
    return path.exists()


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "icons"
    ok = True
    for filename in ICON_SIZES:
        path = out_dir / filename
        done = render_icon(filename, path)
        print(f"{filename}: {'OK' if done else 'FAILED'} ({path})")
        ok = ok and done
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
