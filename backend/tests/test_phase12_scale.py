# ====================================================================
# Phase 12 tests: l10n + portfolio + multi-product + mass lead gen
# ====================================================================
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier
from backend import business_db
from backend.config import settings


# --------------------------------------------------------------------
# Plugins register
# --------------------------------------------------------------------

def test_phase12_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.l10n.plugin",
        "plugins.portfolio.plugin",
        "plugins.agency_orchestrator.plugin",
        "plugins.ecommerce.plugin",
        "plugins.website.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    required = [
        "l10n.profile", "l10n.convert_currency", "l10n.format_money",
        "l10n.arabicize_number", "l10n.detect_language", "l10n.localized_content",
        "portfolio.add_business", "portfolio.list_businesses", "portfolio.kpis",
        "portfolio.dashboard", "portfolio.cap_available",
        "agency.build_multi_product", "agency.run_continuous", "agency.mass_lead_gen",
        "agency.portfolio_status",
        "ecommerce.notify_customer", "ecommerce.order_status_update_with_notify",
        "ecommerce.generate_tracking_page", "ecommerce.list_notifications",
    ]
    missing = [r for r in required if r not in names]
    assert not missing, f"missing: {missing}"


# --------------------------------------------------------------------
# Localization
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_l10n_profile_returns_jordan_defaults():
    import plugins.l10n.plugin as l10n
    profile = await l10n.l10n_profile()
    assert profile["ok"] is True
    assert profile["country"] == "JO"
    assert profile["currency"] == "JOD"
    assert profile["rtl"] is True
    assert profile["language"] == "ar"


@pytest.mark.asyncio
async def test_l10n_currency_conversion_usd_to_jod():
    import plugins.l10n.plugin as l10n
    result = await l10n.l10n_convert_currency(amount=100, from_currency="USD", to_currency="JOD")
    assert result["ok"] is True
    assert result["original_currency"] == "USD"
    assert result["converted_currency"] == "JOD"
    # 100 USD * 1.0 / 1.41 ≈ 70.92 JOD
    assert 70 < result["converted_amount"] < 75


@pytest.mark.asyncio
async def test_arabicize_number_converts_digits():
    import plugins.l10n.plugin as l10n
    assert l10n.arabicize_number("12345") == "١٢٣٤٥"
    assert l10n.arabicize_number("0") == "٠"
    assert l10n.arabicize_number("Price: 99.50 USD") == "Price: ٩٩.٥٠ USD"


@pytest.mark.asyncio
async def test_format_money_with_arabic_digits():
    import plugins.l10n.plugin as l10n
    result = await l10n.l10n_format_money(amount=49.99, currency="JOD", arabic_digits=True, locale="ar")
    assert result["ok"] is True
    assert "د.أ" in result["formatted"]
    # Should contain Arabic-Indic digits.
    assert any(ch in result["formatted"] for ch in "٠١٢٣٤٥٦٧٨٩")


@pytest.mark.asyncio
async def test_detect_language_arabic_vs_english():
    import plugins.l10n.plugin as l10n
    ar = await l10n.l10n_detect_language("مرحباً سيدي، كيف يمكنني مساعدتك اليوم؟")
    assert ar["language"] == "ar"
    en = await l10n.l10n_detect_language("Hello Sir, how can I help you today?")
    assert en["language"] == "en"


# --------------------------------------------------------------------
# Portfolio — 50-business cap + KPIs
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portfolio_add_then_cap_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    # Patch the cap down so we don't actually add 50 businesses.
    import plugins.portfolio.plugin as pf
    monkeypatch.setattr(settings, "portfolio_max_businesses", 3)

    for i in range(3):
        r = await pf.portfolio_add_business(name=f"Biz {i}", niche="test")
        assert r["ok"] is True
    cap = await pf.portfolio_cap_available()
    assert cap["remaining"] == 0
    # 4th should be refused.
    r = await pf.portfolio_add_business(name="Biz 4", niche="test")
    assert r["ok"] is False
    assert "cap" in r["error"].lower()


@pytest.mark.asyncio
async def test_portfolio_dashboard_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.portfolio.plugin as pf
    await pf.portfolio_add_business(name="A", niche="x", monetization="saas")
    await pf.portfolio_add_business(name="B", niche="y", monetization="service", currency="USD")
    dash = await pf.portfolio_dashboard(days=30)
    assert dash["ok"] is True
    assert dash["total_businesses"] == 2
    assert dash["capacity"] == settings.portfolio_max_businesses
    assert "JOD" in dash["by_currency"]


# --------------------------------------------------------------------
# Website — Arabic + RTL
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_website_landing_page_arabic_rtl(tmp_path):
    import plugins.website.plugin as ws
    r = await ws.website_generate_landing_page(
        product_name="منتج تجريبي", tagline="أفضل منتج",
        description="وصف عربي للمنتج.",
        features=["ميزة ١", "ميزة ٢", "ميزة ٣"],
        pricing=[{"name": "أساسي", "price": "29 د.أ", "features": ["a", "b"]}],
        language="ar", rtl=True,
        output_dir=str(tmp_path),
    )
    assert r["ok"] is True
    html = Path(r["path"]).read_text(encoding="utf-8")
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html
    assert "Tajawal" in html  # Arabic webfont
    assert "منتج تجريبي" in html


# --------------------------------------------------------------------
# Ecommerce — customer notifications + tracking page
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_order_status_with_notify_records_notification(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.ecommerce.plugin as ec

    # Setup product + order with a customer email so notifications can fire.
    prod = await ec.ecommerce_add_product(name="X", price=10, inventory=5)
    order = await ec.ecommerce_create_order(
        customer_name="زبون", sku=prod["sku"], quantity=1,
        customer_email="customer@example.com",
    )
    assert order["ok"]

    # Patch the email_send to not actually send (no SMTP in tests).
    async def fake_email_send(**kwargs):
        return {"ok": True, "sent": True}
    import plugins.communication.plugin as comm
    monkeypatch.setattr(comm, "email_send", fake_email_send)

    upd = await ec.ecommerce_order_status_update_with_notify(
        order_id=order["order_id"], status="paid", language="ar",
    )
    assert upd["ok"] is True
    assert upd["notified"] is True

    # Verify notification was logged.
    notifs = await ec.ecommerce_list_notifications(order_id=order["order_id"])
    assert notifs["count"] == 1
    assert "تأكيد" in notifs["notifications"][0]["subject"]  # Arabic subject


@pytest.mark.asyncio
async def test_tracking_page_is_arabic_rtl(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.ecommerce.plugin as ec

    prod = await ec.ecommerce_add_product(name="X", price=10, inventory=5)
    order = await ec.ecommerce_create_order(customer_name="زبون", sku=prod["sku"], quantity=1)
    page = await ec.ecommerce_generate_tracking_page(order_id=order["order_id"], output_dir=str(tmp_path))
    assert page["ok"] is True
    html = Path(page["path"]).read_text(encoding="utf-8")
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html
    assert "تتبع الطلب" in html  # Arabic title


# --------------------------------------------------------------------
# Agency — mass lead gen accepts large target
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mass_lead_gen_param_validation(tmp_path, monkeypatch):
    """Without network we just verify the tool accepts target_count=50+."""
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.agency_orchestrator.plugin as ao
    # Mock the underlying sales_find_leads to avoid network.
    async def fake_find_leads(**kwargs):
        return {"ok": True, "count": 0, "leads": []}
    import plugins.sales.plugin as sales
    monkeypatch.setattr(sales, "sales_find_leads", fake_find_leads)

    result = await ao.agency_mass_lead_gen(
        niche="restaurants", location="Amman, Jordan", target_count=50,
    )
    assert result["ok"] is True
    assert result["target_count"] == 50


# --------------------------------------------------------------------
# Agency — continuous mode toggle
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_continuous_mode_toggle(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.agency_orchestrator.plugin as ao

    activate = await ao.agency_run_continuous(activate=True, products_per_business=5)
    assert activate["ok"] is True
    assert activate["mode"] == "always_on"

    state = business_db.query_one("SELECT * FROM continuous_state ORDER BY id DESC LIMIT 1")
    assert state is not None
    assert state["mode"] == "always_on"

    pause = await ao.agency_run_continuous(activate=False)
    assert pause["mode"] == "paused"
