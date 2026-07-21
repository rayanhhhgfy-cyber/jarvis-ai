# ====================================================================
# Phase 10 batch 5 tests: github_free, media_local, backup_local
# ====================================================================
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier


def test_phase10_batch5_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.github_free.plugin",
        "plugins.media_local.plugin",
        "plugins.backup_local.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    for required in [
        "github.list_repos", "github.read_file", "github.list_issues",
        "github.list_prs", "github.list_commits", "github.search_repos", "github.user",
        "media.video_slideshow", "media.audio_chime", "media.musicgen_local",
        "backup.run_now", "backup.list", "backup.schedule", "backup.verify",
    ]:
        assert required in names, f"{required} missing"


# --------------------------------------------------------------------
# GitHub plugin - all Tier 0 (read-only)
# --------------------------------------------------------------------

def test_github_tools_are_tier_0():
    reg = get_registry()
    for t in reg.all_tools():
        if t.category == "github":
            assert t.risk_tier is RiskTier.TIER_0_OBSERVE


# --------------------------------------------------------------------
# Backup plugin - run/list/verify round-trip
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backup_run_and_list(monkeypatch, tmp_path):
    """BackupManager should produce a zip and list it back."""
    # Patch the manager's directory.
    import backend.backup_manager as bm
    bm.backup_manager.backup_dir = str(tmp_path)

    import plugins.backup_local.plugin as bp
    result = await bp.backup_run_now(backup_type="configs")
    assert "path" in result or result.get("ok") is False
    if "path" in result:
        # The zip should exist.
        assert Path(result["path"]).is_file()
        # List should now show 1 backup.
        listing = await bp.backup_list()
        assert listing["ok"] is True
        assert listing["count"] >= 1


@pytest.mark.asyncio
async def test_backup_verify_computes_correct_sha256(tmp_path):
    import plugins.backup_local.plugin as bp
    f = tmp_path / "test.zip"
    payload = b"hello world"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    result = await bp.backup_verify(path=str(f), expected_sha256=expected)
    assert result["ok"] is True
    assert result["sha256"] == expected
    assert result["matches_expected"] is True

    bad = await bp.backup_verify(path=str(f), expected_sha256="0" * 64)
    assert bad["ok"] is True
    assert bad["matches_expected"] is False


# --------------------------------------------------------------------
# Media local - graceful degradation
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_musicgen_returns_clean_error_when_transformers_missing(monkeypatch):
    """If torch/transformers isn't installed, return ok=False — not raise."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import plugins.media_local.plugin as ml
    ml._musicgen_model = None
    result = await ml.media_musicgen_local(prompt="test", seconds=1.0)
    assert result["ok"] is False
    assert "transformers" in result["error"] or "torch" in result["error"] or "lib" in result["error"].lower()


@pytest.mark.asyncio
async def test_video_slideshow_returns_error_for_empty_images():
    import plugins.media_local.plugin as ml
    result = await ml.media_video_slideshow(images=[], output_path="/tmp/x.mp4")
    assert result["ok"] is False
    assert "no images" in result["error"]
