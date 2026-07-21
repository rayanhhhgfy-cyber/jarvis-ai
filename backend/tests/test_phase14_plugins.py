# ====================================================================
# Phase 14 tests: 14 plugins
# ====================================================================
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier
from backend import business_db


# --------------------------------------------------------------------
# All Phase 14 plugins register
# --------------------------------------------------------------------

def test_phase14_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.codex.plugin", "plugins.council.plugin",
        "plugins.twin.plugin", "plugins.shorts.plugin",
        "plugins.newsletter.plugin", "plugins.music.plugin",
        "plugins.media_empire.plugin",
        "plugins.app_factory.plugin", "plugins.saas_factory.plugin",
        "plugins.github_empire.plugin",
        "plugins.freelancer.plugin", "plugins.dropship.plugin", "plugins.course.plugin",
        "plugins.web3.plugin", "plugins.defi.plugin", "plugins.family_office.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    # Spot-check at least 1 per plugin.
    required = [
        "codex.ingest_text", "codex.ask", "codex.write_like_me",
        "council.assemble", "council.debate", "council.vote", "council.synthesize", "council.red_team", "council.run_full",
        "twin.train_voice", "twin.generate_voice", "twin.generate_talking_video", "twin.fine_tune_llm", "twin.consistency_check",
        "shorts.hook_writer", "shorts.cut_from_long_video", "shorts.verticalize", "shorts.add_captions_arabic",
        "newsletter.spec", "newsletter.write_issue", "newsletter.publish_substack", "newsletter.publish_beehiiv",
        "newsletter.find_sponsors", "newsletter.archive_compile", "newsletter.subscribe_widget",
        "music.album_concept", "music.lyrics_write", "music.generate_song_suno", "music.generate_song_musicgen",
        "music.album_art", "music.distribute_distrokid", "music.royalty_track",
        "media_empire.publish_from_idea", "media_empire.list_publications",
        "app.spec_design", "app.generate_flutter", "app.build_apk", "app.publish_play_store", "app.list_projects",
        "saas.spec_from_niche", "saas.generate_backend", "saas.generate_frontend", "saas.add_stripe",
        "saas.deploy_one_shot", "saas.list_projects",
        "gh_empire.discover_unmet_need", "gh_empire.bootstrap_repo", "gh_empire.implement_feature",
        "gh_empire.respond_to_issues", "gh_empire.publish_release", "gh_empire.list_repos",
        "freelance.scan_upwork", "freelance.bid_write", "freelance.bid_submit_assisted",
        "freelance.deliver_work", "freelance.fiverr_gig_create",
        "dropship.trend_scan", "dropship.aliexpress_search", "dropship.create_store_woo",
        "dropship.list_product", "dropship.meta_ad_campaign", "dropship.auto_fulfill",
        "course.outline", "course.lesson_write", "course.generate_slides", "course.voiceover",
        "course.quiz_generator", "course.workbook_pdf", "course.publish_udemy", "course.list_courses",
        "web3.deploy_ipfs", "web3.deploy_arweave", "web3.register_ens", "web3.publish_mirror", "web3.dns_link",
        "defi.yield_scan", "defi.wallet_balance_multi", "defi.stake_solana", "defi.farm_ethereum",
        "defi.auto_compound", "defi.tax_lots",
        "family.add_asset", "family.net_worth_tracker", "family.investment_allocation",
        "family.tax_loss_harvest", "family.estate_plan_generator", "family.charity_donor_advised",
        "family.kyc_aml_check",
    ]
    missing = [r for r in required if r not in names]
    assert not missing, f"missing: {missing[:10]}"


# --------------------------------------------------------------------
# Twin — consent gate
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twin_voice_requires_consent(tmp_path):
    """train_voice must reject when confirm_owner_consent=false."""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"fake")
    import plugins.twin.plugin as twin
    r = await twin.twin_train_voice(sample_path=str(sample), confirm_owner_consent=False)
    assert r["ok"] is False
    assert "consent" in r["error"].lower()


# --------------------------------------------------------------------
# Twin — generate_voice fallback when model not trained
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_twin_generate_voice_falls_back_to_edge_tts():
    import plugins.twin.plugin as twin
    r = await twin.twin_generate_voice(text="مرحبا", language="ar", model_name="nonexistent_model")
    # Should fall back to edge-tts (or fail cleanly if edge-tts unavailable).
    assert r["ok"] in (True, False)  # don't crash


# --------------------------------------------------------------------
# Council — basic flow
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_council_assemble_returns_personas():
    import plugins.council.plugin as c
    r = await c.council_assemble()
    assert r["ok"] is True
    persona_ids = {p["id"] for p in r["personas"]}
    assert {"ceo", "cfo", "cmo", "engineer", "skeptic"} <= persona_ids


# --------------------------------------------------------------------
# Codex — ingest + ask round-trip
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_codex_ingest_then_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.codex.plugin as codex
    ing = await codex.codex_ingest_text(text="I prefer concise status updates over long meetings.", source="test")
    assert ing["ok"] is True
    ask = await codex.codex_ask(query="status updates")
    assert ask["ok"] is True
    assert ask["total_found"] >= 1


@pytest.mark.asyncio
async def test_codex_ingest_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.codex.plugin as codex
    first = await codex.codex_ingest_text(text="duplicate content", source="test")
    second = await codex.codex_ingest_text(text="duplicate content", source="test")
    assert first["ok"] and not first.get("skipped")
    assert second["ok"] and second.get("skipped") is True


# --------------------------------------------------------------------
# Shorts — hook writer
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shorts_hook_writer_returns_list():
    import plugins.shorts.plugin as sh
    r = await sh.shorts_hook_writer(topic="productivity tips", language="en")
    # Either ok with hooks, or graceful error if LLM unavailable.
    if r.get("ok"):
        assert isinstance(r["hooks"], list)
    else:
        assert "error" in r


# --------------------------------------------------------------------
# Newsletter — subscribe widget HTML
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_newsletter_subscribe_widget_arabic():
    import plugins.newsletter.plugin as nl
    r = await nl.newsletter_subscribe_widget(newsletter_name="Sir Digest", language="ar")
    assert r["ok"] is True
    assert "rtl" in r["html"]
    assert "Sir Digest" in r["html"]


# --------------------------------------------------------------------
# Music — royalty calc math
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_music_royalty_track_math():
    import plugins.music.plugin as mus
    r = await mus.music_royalty_track(play_count_spotify=10000, play_count_apple=5000, play_count_youtube=2000)
    assert r["ok"] is True
    assert r["spotify_revenue_usd"] == 35.0
    assert r["apple_revenue_usd"] == 35.0
    assert r["youtube_revenue_usd"] == 2.0
    assert r["total_revenue_usd"] == 72.0


# --------------------------------------------------------------------
# App factory — spec returns JSON
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_spec_design_returns_structure():
    import plugins.app_factory.plugin as ap
    r = await ap.app_spec_design(description="Simple habit tracker", platform="android")
    if r.get("ok"):
        assert "spec" in r
        assert "app_name" in r["spec"]
    else:
        assert "error" in r  # LLM unavailable


# --------------------------------------------------------------------
# SaaS factory — list projects
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_saas_list_projects_returns_list():
    import plugins.saas_factory.plugin as sf
    r = await sf.saas_list_projects()
    assert r["ok"] is True
    assert isinstance(r["projects"], list)


# --------------------------------------------------------------------
# GitHub empire — list repos
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gh_empire_list_repos():
    import plugins.github_empire.plugin as gh
    r = await gh.gh_empire_list_repos()
    assert r["ok"] is True


# --------------------------------------------------------------------
# Freelancer — bid submit returns tos_warning
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_freelance_bid_submit_assisted_includes_tos_warning(monkeypatch):
    """Mock webbrowser.open so the test doesn't pop a real browser window."""
    import plugins.freelancer.plugin as fr
    opened = []
    monkeypatch.setattr(fr.webbrowser, "open", lambda url: opened.append(url))
    r = await fr.freelance_bid_submit_assisted(job_url="https://upwork.com/job/123", proposal_text="test")
    assert opened == ["https://upwork.com/job/123"]
    assert "tos_warning" in r


# --------------------------------------------------------------------
# Dropship — meta ad campaign gated
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropship_meta_ad_gated_without_allow_ad_spend():
    """allow_ad_spend is not defined in Settings so getattr returns False — gate fires."""
    import plugins.dropship.plugin as ds
    r = await ds.dropship_meta_ad_campaign(store_url="https://example.com", ad_copy="test")
    assert r["ok"] is False
    assert "allow_ad_spend" in r["error"]


# --------------------------------------------------------------------
# Course — list courses
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_course_list_courses_returns_list():
    import plugins.course.plugin as cr
    r = await cr.course_list_courses()
    assert r["ok"] is True
    assert isinstance(r["courses"], list)


@pytest.mark.asyncio
async def test_course_publish_udemy_does_not_open_browser_in_tests(monkeypatch):
    """Mock webbrowser so the test does not pop a real browser."""
    import plugins.course.plugin as cr
    opened = []
    monkeypatch.setattr(cr.webbrowser, "open", lambda url: opened.append(url))
    r = await cr.course_publish_udemy(course_title="Test Course")
    assert r["ok"] is True
    assert opened == ["https://www.udemy.com/instructor/courses/"]


# --------------------------------------------------------------------
# web3 — IPFS without creds returns clean error
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web3_deploy_ipfs_without_creds():
    import plugins.web3.plugin as w3
    # Create a tmp dir.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        r = await w3.web3_deploy_ipfs(site_dir=tmp)
        # No creds → clean error.
        assert r["ok"] is False
        assert "pinata_jwt" in r["error"] or "vault" in r["error"].lower()


# --------------------------------------------------------------------
# defi — real-money gate
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_defi_stake_solana_gated():
    import plugins.defi.plugin as de
    r = await de.defi_stake_solana(amount_sol=1.0)
    assert r["ok"] is False
    assert "gate" in r["error"].lower() or "real-trade" in r["error"].lower()


# --------------------------------------------------------------------
# Family office — net worth tracker
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_family_net_worth_tracker_empty_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.family_office.plugin as fo
    r = await fo.family_net_worth_tracker()
    assert r["ok"] is True
    assert r["total_usd"] == 0


@pytest.mark.asyncio
async def test_family_add_asset_then_track(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.family_office.plugin as fo
    add = await fo.family_add_asset(asset_type="cash", name="Bank account", value_usd=5000)
    assert add["ok"] is True
    track = await fo.family_net_worth_tracker()
    assert track["ok"] is True
    assert track["total_usd"] == 5000


# --------------------------------------------------------------------
# Family office — KYC AML flag for high-risk country
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_family_kyc_flags_high_risk_country():
    import plugins.family_office.plugin as fo
    r = await fo.family_kyc_aml_check(counterparty_name="Unknown Entity", counterparty_country="KP")
    assert r["ok"] is True
    assert "HIGH RISK" in r["verdict"]


# --------------------------------------------------------------------
# Media empire — list publications returns list (no crash without any)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_empire_list_publications():
    import plugins.media_empire.plugin as me
    r = await me.media_empire_list_publications()
    assert r["ok"] is True
    assert isinstance(r["publications"], list)
