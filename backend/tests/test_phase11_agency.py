# ====================================================================
# Phase 11 tests: business agency plugins
# ====================================================================
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier
from backend import business_db


# --------------------------------------------------------------------
# All 8 Phase 11 plugins register
# --------------------------------------------------------------------

def test_phase11_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.marketing.plugin",
        "plugins.sales.plugin",
        "plugins.support.plugin",
        "plugins.ecommerce.plugin",
        "plugins.website.plugin",
        "plugins.business_intel.plugin",
        "plugins.payments.plugin",
        "plugins.agency_orchestrator.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    required = [
        "marketing.create_content", "marketing.post", "marketing.schedule",
        "sales.add_client", "sales.find_leads", "sales.create_pitch_deck",
        "support.create_ticket", "support.sentiment_analyze",
        "ecommerce.add_product", "ecommerce.create_order", "ecommerce.lookup_tracking",
        "website.generate_landing_page", "website.seo_audit",
        "biz.scan_opportunities", "biz.list_opportunities", "biz.research_market",
        "payments.create_invoice", "payments.create_stripe_link", "payments.revenue_summary",
        "agency.find_new_business", "agency.onboard_client", "agency.build_project",
        "agency.run_full_funnel", "agency.weekly_report",
    ]
    missing = [r for r in required if r not in names]
    assert not missing, f"missing: {missing}"


# --------------------------------------------------------------------
# Business DB round-trip
# --------------------------------------------------------------------

def test_business_db_initialize_creates_all_tables(tmp_path, monkeypatch):
    """A fresh DB at an alternate path should have all 11 tables."""
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    rows = business_db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    names = {r[0] for r in rows}
    for required in {"clients", "contacts", "deals", "campaigns", "posts", "tickets",
                     "products", "orders", "invoices", "opportunities", "audit_log"}:
        assert required in names


# --------------------------------------------------------------------
# Marketing — sentiment / classification
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_marketing_post_unknown_platform_rejected():
    import plugins.marketing.plugin as m
    result = await m.marketing_post(platform="myspace", content="hi")
    assert result["ok"] is False
    assert "unknown platform" in result["error"]


@pytest.mark.asyncio
async def test_marketing_post_reddit_requires_subreddit():
    import plugins.marketing.plugin as m
    result = await m.marketing_post(platform="reddit", content="hi")
    assert result["ok"] is False
    assert "subreddit" in result["error"]


# --------------------------------------------------------------------
# Sales — CRM round-trip
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sales_add_client_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.sales.plugin as s
    add = await s.sales_add_client(name="Acme Corp", niche="AI tools", status="active")
    assert add["ok"] is True
    listing = await s.sales_list_clients(status="active")
    assert listing["count"] >= 1
    assert listing["clients"][0]["name"] == "Acme Corp"


# --------------------------------------------------------------------
# Support — sentiment + ticket flow
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_support_sentiment_rules():
    import plugins.support.plugin as sp
    pos = await sp.support_sentiment_analyze("This is amazing! I love it, thank you so much.")
    assert pos["sentiment"] == "positive"
    neg = await sp.support_sentiment_analyze("This is broken and awful, I hate it. Refund please.")
    assert neg["sentiment"] == "negative"
    neu = await sp.support_sentiment_analyze("The package arrived on Tuesday.")
    assert neu["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_support_ticket_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.support.plugin as sp
    create = await sp.support_create_ticket(subject="Order missing", body="where is it?", priority="high")
    assert create["ok"] is True
    resp = await sp.support_respond_to_ticket(ticket_id=create["ticket_id"], response="Refunding now.", new_status="resolved")
    assert resp["ok"] is True
    assert resp["status"] == "resolved"
    listing = await sp.support_list_tickets(status="resolved")
    assert listing["count"] == 1


# --------------------------------------------------------------------
# Ecommerce — product + order flow
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ecommerce_product_order_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.ecommerce.plugin as ec

    # Add a product
    prod = await ec.ecommerce_add_product(name="Widget", price=29.99, inventory=10)
    assert prod["ok"] is True

    # Create order — should decrement inventory
    order = await ec.ecommerce_create_order(customer_name="John Doe", sku=prod["sku"], quantity=2)
    assert order["ok"] is True
    assert order["total"] == 59.98

    # Inventory should be 8 now
    inv = await ec.ecommerce_update_inventory(sku=prod["sku"], delta=0)
    assert inv["product"]["inventory"] == 8


@pytest.mark.asyncio
async def test_ecommerce_order_rejects_insufficient_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.ecommerce.plugin as ec
    prod = await ec.ecommerce_add_product(name="Rare", price=100, inventory=1)
    order = await ec.ecommerce_create_order(customer_name="x", sku=prod["sku"], quantity=5)
    assert order["ok"] is False
    assert "insufficient" in order["error"]


@pytest.mark.asyncio
async def test_tracking_lookup_auto_detects_carrier():
    import plugins.ecommerce.plugin as ec
    usps = await ec.ecommerce_lookup_tracking(tracking_number="9400111899223100123456")
    assert usps["carrier"] == "usps"
    ups = await ec.ecommerce_lookup_tracking(tracking_number="1Z999AA10123456784")
    assert ups["carrier"] == "ups"


# --------------------------------------------------------------------
# Website — landing page generation
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_website_generate_landing_page_creates_html(tmp_path):
    import plugins.website.plugin as ws
    result = await ws.website_generate_landing_page(
        product_name="TestProd", tagline="The best test product",
        description="A genuinely useful product.",
        features=["Fast", "Cheap", "Reliable"],
        pricing=[{"name": "Pro", "price": "$49", "features": ["a", "b"]}],
        output_dir=str(tmp_path),
    )
    assert result["ok"] is True
    html = Path(result["path"]).read_text(encoding="utf-8")
    assert "TestProd" in html
    assert "tailwindcss" in html  # CDN present
    assert "Pro" in html
    assert "Reliable" in html


# --------------------------------------------------------------------
# Business intel — opportunity scanner dedup
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opportunity_scanner_dedupes_by_url(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.business_intel.plugin as bi
    # Insert one manually.
    business_db.execute(
        "INSERT INTO opportunities (source, title, url, niche, score, status, discovered_at) "
        "VALUES ('test', 'dup', 'https://example.com/x', 'test', 50, 'new', ?)",
        (datetime.utcnow().isoformat(),),
    )
    # Run scanner with mocked source data pointing at the same URL.
    async def fake_hn(limit):
        return [{"source": "hackernews", "title": "dup", "url": "https://example.com/x",
                 "score": 100, "comments": 50, "external_id": "1"}]
    async def fake_reddit(subs, lim):
        return []
    monkeypatch.setattr(bi, "_scan_hn", fake_hn)
    monkeypatch.setattr(bi, "_scan_reddit", fake_reddit)

    result = await bi.biz_scan_opportunities(niche_keywords=["test"])
    assert result["ok"] is True
    assert result["added"] == 0  # deduped


# --------------------------------------------------------------------
# Payments — invoice numbering + revenue summary
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invoice_numbers_increment_within_year(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    # Create a fake client row.
    cid = business_db.execute(
        "INSERT INTO clients (name, status, created_at) VALUES (?, 'active', ?)",
        ("Test", datetime.utcnow().isoformat()),
    )
    import plugins.payments.plugin as p
    inv1 = await p.payments_create_invoice(client_id=cid, amount=100)
    inv2 = await p.payments_create_invoice(client_id=cid, amount=200)
    assert inv1["number"] != inv2["number"]
    year = datetime.utcnow().year
    assert inv1["number"].startswith(f"INV-{year}-")


@pytest.mark.asyncio
async def test_revenue_summary_empty_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.payments.plugin as p
    result = await p.payments_revenue_summary(days=30)
    assert result["ok"] is True
    assert result["by_currency"] == []


# --------------------------------------------------------------------
# Agency orchestrator — onboarding flow (mocked)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agency_onboard_client_creates_full_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(business_db, "_DB_PATH", tmp_path / "biz.db")
    business_db.initialize()
    import plugins.agency_orchestrator.plugin as ao
    result = await ao.agency_onboard_client(
        client_name="TestCo", niche="AI marketing", contact_email="ceo@testco.com",
    )
    assert result["ok"] is True
    assert result["client_id"] > 0
    assert result["contact_id"] > 0
    assert result["deal_id"] > 0
    assert len(result["campaign_ids"]) >= 1
    assert "Welcome" in result["welcome_email_subject"]
