# ====================================================================
# JARVIS OMEGA — Test Financial Ledger (Phase 1)
# ====================================================================

import pytest
from backend.ledger import ledger
from backend.business_db import execute, query_one


def test_ledger_record_entry_credit_and_debit():
    c_id = ledger.record_entry(
        entry_type="credit",
        amount=150.0,
        category="stripe_payment",
        currency="USD",
        business_id=1,
        source_event="stripe_charge",
        reference_id="ch_12345",
    )
    assert c_id > 0

    d_id = ledger.record_entry(
        entry_type="debit",
        amount=50.0,
        category="ad_spend",
        currency="USD",
        business_id=1,
        source_event="facebook_ads",
        reference_id="ad_67890",
    )
    assert d_id > 0

    balance = ledger.get_business_balance(1)
    assert balance["total_credits"] >= 150.0
    assert balance["total_debits"] >= 50.0
    assert balance["net_balance"] >= 100.0


def test_ledger_portfolio_balance():
    ledger.record_entry(entry_type="credit", amount=200.0, category="service_fee", business_id=2)
    portfolio = ledger.get_portfolio_balance()
    assert portfolio["total_credits"] >= 350.0
    assert portfolio["net_balance"] > 0


def test_ledger_spend_by_category():
    ledger.record_entry(entry_type="debit", amount=30.0, category="api_fee", business_id=1)
    spend_cats = ledger.get_spend_by_category(business_id=1)
    categories = [s["category"] for s in spend_cats]
    assert "ad_spend" in categories
    assert "api_fee" in categories


import uuid

def test_ledger_reconciliation():
    # Insert dummy client first to satisfy foreign key constraint
    client_id = execute(
        "INSERT INTO clients (name, created_at) VALUES ('Test Client', '2026-08-01T00:00:00')",
    )
    # Insert dummy paid order with client_id
    execute(
        "INSERT INTO orders (client_id, customer_name, total, currency, status, created_at) VALUES (?, 'John', 99.0, 'USD', 'paid', '2026-08-01T00:00:00')",
        (client_id,),
    )
    inv_num = f"INV-TEST-{uuid.uuid4().hex[:6]}"
    execute(
        "INSERT INTO invoices (client_id, number, amount, currency, status, created_at) VALUES (?, ?, 500.0, 'USD', 'paid', '2026-08-01T00:00:00')",
        (client_id, inv_num),
    )

    res = ledger.reconcile_on_first_run()
    if res["reconciled"]:
        assert res["entries_added"] >= 2
    else:
        assert res["reason"] == "Already reconciled"
