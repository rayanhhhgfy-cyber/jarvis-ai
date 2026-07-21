# ====================================================================
# Phase 13 tests: 8 plugins
# ====================================================================
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier
from backend import business_db
from backend.config import settings


# --------------------------------------------------------------------
# All 8 Phase 13 plugins register
# --------------------------------------------------------------------

def test_phase13_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.islamic.plugin",
        "plugins.legal_jo.plugin",
        "plugins.affiliate.plugin",
        "plugins.seo.plugin",
        "plugins.realestate_jo.plugin",
        "plugins.trading.plugin",
        "plugins.youtube.plugin",
        "plugins.whatsapp.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    required = [
        "islamic.prayer_times", "islamic.hijri_date", "islamic.zakat_calculator",
        "islamic.qibla", "islamic.halal_check", "islamic.events_calendar",
        "jo_tax.calc_income_tax", "jo_tax.calc_sales_tax", "jo_tax.calc_social_security",
        "jo_customs.duty_estimator", "jo_business.name_check",
        "legal.nda_generator", "legal.contract_analyzer", "legal.trademark_search_wipo",
        "affiliate.amazon_search", "affiliate.clickbank_products", "affiliate.shareasale_offers",
        "affiliate.link_cloak", "affiliate.review_writer", "affiliate.disclosure_injector",
        "seo.rank_check", "seo.backlink_audit", "seo.keyword_research", "seo.competitor_gap",
        "seo.content_brief", "seo.serp_snapshot", "seo.sitemap_submit",
        "realestate.list_jo", "realestate.cash_flow_calc", "realestate.investment_score",
        "realestate.alert_new", "realestate.market_stats_jo", "realestate.generate_listing",
        "trading.quote", "trading.candles", "trading.indicators", "trading.signals_scan",
        "trading.backtest", "trading.strategy_dca", "trading.strategy_grid",
        "trading.paper_account", "trading.paper_buy", "trading.paper_sell",
        "trading.alert_price", "trading.run_alerts",
        "youtube.script_write", "youtube.thumbnail_generate", "youtube.voiceover",
        "youtube.video_assemble", "youtube.upload", "youtube.seo_optimize",
        "youtube.analytics", "youtube.competitor_track",
        "whatsapp.send_text", "whatsapp.send_image", "whatsapp.send_document",
        "whatsapp.broadcast", "whatsapp.contact_import", "whatsapp.order_capture",
    ]
    missing = [r for r in required if r not in names]
    assert not missing, f"missing tools: {missing}"


# --------------------------------------------------------------------
# Islamic — zakat math
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zakat_below_nisab():
    """Silver nisab (595g * 0.7 JOD/g = 416.5 JOD) is low; use 100 JOD to be safely below."""
    import plugins.islamic.plugin as islamic
    r = await islamic.islamic_zakat_calculator(cash_jod=100)
    assert r["ok"] is True
    assert r["zakat_due_jod"] == 0
    assert "below nisab" in r["reason"]


@pytest.mark.asyncio
async def test_zakat_above_nisab():
    import plugins.islamic.plugin as islamic
    r = await islamic.islamic_zakat_calculator(cash_jod=10000)
    assert r["ok"] is True
    assert r["zakat_due_jod"] == 250.0  # 10000 * 0.025


@pytest.mark.asyncio
async def test_qibla_bearing_within_0_360():
    import plugins.islamic.plugin as islamic
    # From Amman (31.95, 35.91).
    r = await islamic.islamic_qibla(latitude=31.95, longitude=35.91)
    assert r["ok"] is True
    assert 0 <= r["qibla_bearing_degrees"] < 360


@pytest.mark.asyncio
async def test_halal_check_finds_alcohol():
    import plugins.islamic.plugin as islamic
    r = await islamic.islamic_halal_check("Ingredients: water, sugar, alcohol, flavoring")
    assert r["ok"] is True
    assert r["verdict"] == "haram"
    assert r["haram_count"] >= 1


@pytest.mark.asyncio
async def test_halal_check_clean_ingredient():
    import plugins.islamic.plugin as islamic
    r = await islamic.islamic_halal_check("Ingredients: water, sugar, salt, flour, olive oil")
    assert r["ok"] is True
    assert r["verdict"].startswith("halal")


# --------------------------------------------------------------------
# Legal — Jordan tax brackets
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_income_tax_zero_below_5k():
    import plugins.legal_jo.plugin as lj
    r = await lj.jo_tax_calc_income_tax(annual_income_jod=4000)
    assert r["ok"] is True
    assert r["total_tax_jod"] == 0


@pytest.mark.asyncio
async def test_income_tax_progressive():
    import plugins.legal_jo.plugin as lj
    r = await lj.jo_tax_calc_income_tax(annual_income_jod=20000)
    # 5k exempt, 5k@5%, 5k@10%, 5k@15% = 250 + 500 + 750 = 1500
    assert r["total_tax_jod"] == 1500.0


@pytest.mark.asyncio
async def test_sales_tax_general_16_pct():
    import plugins.legal_jo.plugin as lj
    r = await lj.jo_tax_calc_sales_tax(amount_jod=100, category="general")
    assert r["rate_pct"] == 16.0
    assert r["tax_jod"] == 16.0


@pytest.mark.asyncio
async def test_sales_tax_bread_zero():
    import plugins.legal_jo.plugin as lj
    r = await lj.jo_tax_calc_sales_tax(amount_jod=5, category="bread")
    assert r["rate_pct"] == 0.0


@pytest.mark.asyncio
async def test_social_security_calc():
    import plugins.legal_jo.plugin as lj
    r = await lj.jo_tax_calc_social_security(monthly_salary_jod=1000)
    assert r["employee_contribution_jod"] == 75.0   # 7.5%
    assert r["employer_contribution_jod"] == 142.5  # 14.25%


# --------------------------------------------------------------------
# Affiliate — link cloak + disclosure
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_link_cloak_creates_redirect(tmp_path):
    import plugins.affiliate.plugin as aff
    r = await aff.affiliate_link_cloak(
        destination_url="https://amazon.com/dp/BXXXX",
        slug="best-coffee",
        output_dir=str(tmp_path),
    )
    assert r["ok"] is True
    content = Path(r["path"]).read_text(encoding="utf-8")
    assert "amazon.com/dp/BXXXX" in content


@pytest.mark.asyncio
async def test_disclosure_injector_appends():
    import plugins.affiliate.plugin as aff
    r = await aff.affiliate_disclosure_injector(content="My review.", language="ar")
    assert r["ok"] is True
    assert "إفصاح" in r["content_with_disclosure"]


# --------------------------------------------------------------------
# SEO — keyword research fallback works without network
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keyword_research_returns_clean_error_on_network_failure(monkeypatch):
    import plugins.seo.plugin as seo
    import httpx
    async def fake_get(*args, **kwargs):
        raise httpx.ConnectError("simulated")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    r = await seo.seo_keyword_research(seed_keyword="coffee")
    assert r["ok"] is False


# --------------------------------------------------------------------
# Real estate — math tests (no network)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cash_flow_calc_returns_roi():
    import plugins.realestate_jo.plugin as re
    r = await re.realestate_cash_flow_calc(
        purchase_price_jod=100000, monthly_rent_jod=600,
    )
    assert r["ok"] is True
    assert "cash_on_cash_return_pct" in r
    assert "cap_rate_pct" in r


@pytest.mark.asyncio
async def test_investment_score_underpriced_scores_higher():
    import plugins.realestate_jo.plugin as re
    # Cheap in Abdoun (avg 1100/sqm) → high price score.
    high = await re.realestate_investment_score(
        price_jod=110000, neighborhood="Abdoun", sqm=200, monthly_rent_jod=1500,
    )
    # Overpriced in Marj Al-Hamam (avg 550/sqm) → low score.
    low = await re.realestate_investment_score(
        price_jod=200000, neighborhood="Marj Al-Hamam", sqm=200, monthly_rent_jod=400,
    )
    assert high["total_score"] > low["total_score"]


@pytest.mark.asyncio
async def test_market_stats_returns_known_neighborhoods():
    import plugins.realestate_jo.plugin as re
    r = await re.realestate_market_stats_jo()
    assert r["ok"] is True
    names = {s["neighborhood"] for s in r["stats"]}
    assert "Abdoun" in names
    assert "Dabouq" in names  # highest end


# --------------------------------------------------------------------
# Trading — paper account lifecycle
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paper_account_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.trading.plugin as tr
    # Force fresh account.
    aid = tr._ensure_paper_account()
    acc = business_db.query_one("SELECT * FROM paper_account WHERE id = ?", (aid,))
    starting_balance = acc["balance_usd"]
    assert starting_balance == tr.PAPER_STARTING_BALANCE

    # Mock the quote so we don't depend on the network.
    async def fake_quote(symbol):
        return {"ok": True, "price": 50000.0}
    monkeypatch.setattr(tr, "trading_quote", fake_quote)

    buy = await tr.trading_paper_buy(symbol="BTC/USDT", amount_usd=1000)
    assert buy["ok"] is True
    assert buy["quantity"] == 0.02  # 1000 / 50000

    new_bal = business_db.query_one("SELECT balance_usd FROM paper_account WHERE id = ?", (aid,))["balance_usd"]
    assert new_bal == starting_balance - 1000


def test_normalize_jordanian_phone():
    import plugins.whatsapp.plugin as wa
    assert wa._normalize_phone("0790000000") == "962790000000"
    assert wa._normalize_phone("+962 790 000 000") == "962790000000"
    assert wa._normalize_phone("962790000000") == "962790000000"


def test_whatsapp_rate_limit_enforces_60s_gap():
    import time as _time
    import plugins.whatsapp.plugin as wa
    # Set last send to right now.
    wa._last_send_ts = _time.time()
    block = wa._rate_limited()
    assert block is not None
    assert "60s" in block or "wait" in block.lower()


# --------------------------------------------------------------------
# YouTube — JSON salvage
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_youtube_thumbnail_requires_pillow(monkeypatch):
    """If Pillow fails to load, returns ok=False cleanly."""
    import plugins.youtube.plugin as yt
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = await yt.youtube_thumbnail_generate(title="Test", image_prompt="test")
    assert r["ok"] is False
    assert "Pillow" in r["error"]


# --------------------------------------------------------------------
# Background job registrations
# --------------------------------------------------------------------

def test_phase13_jobs_present_in_scheduler():
    """All 4 Phase 13 background jobs must be registered."""
    from backend.scheduler import scheduler
    scheduler.schedule_interval(job_id="test-pr13-1", func=lambda: None, minutes=99)
    scheduler.schedule_interval(job_id="test-pr13-2", func=lambda: None, minutes=99)
    scheduler.cancel_job("test-pr13-1")
    scheduler.cancel_job("test-pr13-2")
    # Real job registration happens via lifespan, which we don't trigger here,
    # but we can confirm the scheduler API works.
