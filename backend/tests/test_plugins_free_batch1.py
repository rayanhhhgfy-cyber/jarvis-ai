# ====================================================================
# JARVIS OMEGA — Free Plugin Tests (Phase 10 batch 1: browser, media_free, voice_local)
# ====================================================================
"""
Tests for the first three free-tier plugins. Network tools are mocked;
library-missing paths are simulated by patching imports.
"""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools import get_registry, RiskTier


# --------------------------------------------------------------------
# All three plugins load
# --------------------------------------------------------------------

def test_phase10_batch1_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.browser.plugin",
        "plugins.media_free.plugin",
        "plugins.voice_local.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    # Spot-check at least one tool from each plugin.
    assert "browser.navigate" in names
    assert "media.image_pollinations" in names
    assert "voice.tts_edge" in names


# --------------------------------------------------------------------
# Browser plugin — argument validation, no live browser
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browser_tools_are_tier_0_or_2():
    """Browser tools must be Tier 0 (observe) or Tier 2 (system) per plan."""
    reg = get_registry()
    tiers = {t.name: t.risk_tier for t in reg.all_tools() if t.category == "browser"}
    assert tiers["browser.navigate"] is RiskTier.TIER_0_OBSERVE
    assert tiers["browser.click"] is RiskTier.TIER_2_SYSTEM
    assert tiers["browser.type"] is RiskTier.TIER_2_SYSTEM
    assert tiers["browser.extract"] is RiskTier.TIER_0_OBSERVE
    assert tiers["browser.screenshot"] is RiskTier.TIER_0_OBSERVE


@pytest.mark.asyncio
async def test_browser_navigate_returns_clean_error_when_playwright_missing(monkeypatch):
    """If Playwright is not installed, the tool must return a clear error — not raise."""
    import plugins.browser.plugin as br

    async def fake_ensure():
        raise RuntimeError("playwright is not installed (simulated)")

    monkeypatch.setattr(br, "_ensure_browser", fake_ensure)
    # Reset the cached browser so the tool calls _ensure_browser again.
    await br._close_browser()

    result = await br.browser_navigate("https://example.com")
    assert result["ok"] is False
    assert "playwright" in result["error"].lower() or "simulated" in result["error"].lower()


# --------------------------------------------------------------------
# Media-free plugin — Pillow paths
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_image_resize_round_trip():
    """Resize should accept a base64 PNG and return a smaller base64 PNG."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    # Make a 100x100 red PNG.
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_in = base64.b64encode(buf.getvalue()).decode("ascii")

    import plugins.media_free.plugin as mf
    result = await mf.media_image_resize(b64_in, 50, 50)
    assert result["ok"] is True
    out_bytes = base64.b64decode(result["image_base64"])
    out_img = Image.open(io.BytesIO(out_bytes))
    assert out_img.size == (50, 50)


@pytest.mark.asyncio
async def test_media_image_filter_unknown_filter_returns_error():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        pytest.skip("Pillow not installed")
    # Create a tiny valid image.
    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    import plugins.media_free.plugin as mf
    result = await mf.media_image_filter(b64, "nonexistent_filter")
    assert result["ok"] is False
    assert "unknown filter" in result["error"]


# --------------------------------------------------------------------
# Voice-local plugin — graceful degradation
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_tts_edge_handles_missing_library(monkeypatch):
    """If edge-tts is not installed, return a clear error."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "edge_tts":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import plugins.voice_local.plugin as vl
    result = await vl.voice_tts_edge("hello")
    assert result["ok"] is False
    assert "edge-tts" in result["error"]


@pytest.mark.asyncio
async def test_voice_stt_whisper_local_handles_missing_library(monkeypatch):
    """If faster-whisper is not installed, return a clear error."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Reset cached model.
    import plugins.voice_local.plugin as vl
    vl._whisper_model = None

    result = await vl.voice_stt_whisper_local(base64.b64encode(b"fake audio").decode())
    assert result["ok"] is False
    assert "faster-whisper" in result["error"]


@pytest.mark.asyncio
async def test_voice_tts_edge_rejects_oversized_text():
    import plugins.voice_local.plugin as vl
    result = await vl.voice_tts_edge("x" * 4000)
    assert result["ok"] is False
    assert "3000" in result["error"]
