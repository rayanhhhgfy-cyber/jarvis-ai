# ====================================================================
# JARVIS OMEGA - Payouts & Money Flow (Phase 15)
# ====================================================================
"""
Controls where money goes when JARVIS's businesses earn.

MONEY FLOW REALITY:
  Customer pays → Stripe/Amazon/ClickBank/crypto exchange
                 → those processors deposit to SIR'S linked accounts
                 → JARVIS does NOT hold money
                 → JARVIS TRACKS where it is + can trigger transfers

  payouts.track_all       - aggregate all revenue sources in one view
  payouts.where_is_my_money - show every dollar JARVIS earned + where it landed
  payouts.set_destination  - configure where future revenue should flow
  payouts.transfer_to_wallet - ⚠️ REAL MONEY — initiate a transfer to Sir's wallet
  payouts.revenue_history  - timeline of all money earned
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings


def _cred(key: str) -> Optional[str]:
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except Exception:
        return None


@tool(
    name="payouts.track_all",
    description="Aggregate ALL revenue across every source: paid invoices, Stripe, Amazon, ClickBank, crypto, freelance. Returns total + breakdown.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="payouts",
)
async def payouts_track_all() -> Dict[str, Any]:
    sources: List[Dict[str, Any]] = []

    # 1. Paid invoices (from payments plugin).
    try:
        inv_rows = business_db.query(
            "SELECT currency, COUNT(*) as n, COALESCE(SUM(amount), 0) as total "
            "FROM invoices WHERE status = 'paid' GROUP BY currency"
        )
        for r in inv_rows:
            sources.append({
                "source": "invoices",
                "currency": r["currency"],
                "count": r["n"],
                "total": round(r["total"], 2),
                "status": "received",
                "where": "Your bank (via Stripe or bank transfer)",
            })
    except Exception:
        pass

    # 2. Orders revenue (from ecommerce).
    try:
        order_rows = business_db.query(
            "SELECT currency, COUNT(*) as n, COALESCE(SUM(total), 0) as total "
            "FROM orders WHERE status IN ('paid', 'fulfilled', 'shipped', 'delivered') GROUP BY currency"
        )
        for r in order_rows:
            sources.append({
                "source": "ecommerce_orders",
                "currency": r["currency"],
                "count": r["n"],
                "total": round(r["total"], 2),
                "status": "received",
                "where": "Stripe → your bank (or cash on delivery)",
            })
    except Exception:
        pass

    # 3. Stripe (live API if configured).
    stripe_key = _cred("stripe_secret_key")
    stripe_balance = None
    if stripe_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.stripe.com/v1/balance",
                    auth=(stripe_key, ""),
                )
            if resp.status_code == 200:
                bal = resp.json()
                stripe_balance = {
                    "available_usd": bal.get("available", [{}])[0].get("amount", 0) / 100,
                    "pending_usd": bal.get("pending", [{}])[0].get("amount", 0) / 100,
                }
                sources.append({
                    "source": "stripe_balance",
                    "currency": "USD",
                    "available": stripe_balance["available_usd"],
                    "pending": stripe_balance["pending_usd"],
                    "status": "in_stripe",
                    "where": "Stripe account (auto-transfers to your bank per your Stripe schedule)",
                })
        except Exception:
            pass

    # 4. YouTube revenue (if OAuth configured — needs manual check).
    sources.append({
        "source": "youtube_adshare",
        "status": "check_manually",
        "where": "Google AdSense → your bank (monthly, threshold $100)",
        "url": "https://studio.youtube.com/analytics",
    })

    # 5. Amazon Associates.
    sources.append({
        "source": "amazon_associates",
        "status": "check_manually",
        "where": "Amazon pays via direct deposit or gift card (60-day delay, $10 min)",
        "url": "https://affiliate-program.amazon.com/home/reports",
    })

    # 6. Crypto paper account (not real money).
    try:
        paper = business_db.query_one("SELECT balance_usd, starting_balance_usd FROM paper_account ORDER BY id DESC LIMIT 1")
        if paper:
            pnl = paper["starting_balance_usd"] - paper["balance_usd"]
            sources.append({
                "source": "crypto_paper_pnl",
                "currency": "USD",
                "pnl": round(pnl, 2),
                "status": "PAPER ONLY — not real money",
                "where": "Simulation. Enable execute_real_trade=true for real trading.",
            })
    except Exception:
        pass

    # Total.
    total_usd = sum(s.get("total", 0) for s in sources if s.get("currency") in ("USD", None))
    total_jod = round(total_usd / settings.default_currency_exchange_rate, 2) if settings.default_currency_exchange_rate else 0

    return {
        "ok": True,
        "sources": sources,
        "total_real_usd": round(total_usd, 2),
        "total_real_jod": total_jod,
        "note": "Money NEVER flows through JARVIS. It flows directly from payment processors to YOUR accounts. JARVIS only tracks it.",
    }


@tool(
    name="payouts.where_is_my_money",
    description="Plain-English answer: where is all the money JARVIS has earned? Shows every source + destination.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="payouts",
)
async def payouts_where_is_my_money() -> Dict[str, Any]:
    track = await payouts_track_all()
    if not track.get("ok"):
        return track

    summary_lines: List[str] = []
    for s in track["sources"]:
        if s.get("total"):
            summary_lines.append(f"  • {s['source']}: {s['total']} {s.get('currency', 'USD')} → {s.get('where', 'your account')}")
        elif s.get("available") is not None:
            summary_lines.append(f"  • {s['source']}: {s['available']} available + {s.get('pending', 0)} pending → {s.get('where', '')}")
        elif s.get("status") == "check_manually":
            summary_lines.append(f"  • {s['source']}: check manually at {s.get('url', '')}")

    return {
        "ok": True,
        "answer": (
            f"Sir, here's where your money is:\n" + "\n".join(summary_lines) +
            f"\n\nTotal tracked: ${track.get('total_real_usd', 0)} USD ≈ {track.get('total_real_jod', 0)} JOD\n\n"
            "IMPORTANT: Money NEVER touches JARVIS. Payment processors (Stripe, Amazon, YouTube) "
            "deposit directly into YOUR linked bank accounts. JARVIS only tracks + reports."
        ),
        "sources": track["sources"],
        "total_usd": track.get("total_real_usd", 0),
        "total_jod": track.get("total_real_jod", 0),
    }


@tool(
    name="payouts.set_destination",
    description="Configure where future revenue should flow. Persists Sir's bank/wallet details.",
    parameters={
        "type": "object",
        "properties": {
            "bank_name": {"type": "string", "default": "", "description": "e.g. 'Arab Bank Jordan'"},
            "bank_iban": {"type": "string", "default": "", "description": "Your IBAN (JARVIS stores this encrypted, never logs it plaintext)."},
            "crypto_wallet_address": {"type": "string", "default": "", "description": "BTC/ETH/SOL wallet for crypto payouts."},
            "paypal_email": {"type": "string", "default": ""},
            "preferred_payout_method": {"type": "string", "default": "bank", "enum": ["bank", "crypto", "paypal", "stripe"]},
        },
    },
    risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    category="payouts",
)
async def payouts_set_destination(
    bank_name: str = "", bank_iban: str = "",
    crypto_wallet_address: str = "", paypal_email: str = "",
    preferred_payout_method: str = "bank",
) -> Dict[str, Any]:
    from backend.services.credentials_vault import credentials_vault
    saved = []
    if bank_iban:
        credentials_vault.set("payout_bank_iban", bank_iban, category="payout")
        saved.append("payout_bank_iban")
    if bank_name:
        credentials_vault.set("payout_bank_name", bank_name, category="payout")
        saved.append("payout_bank_name")
    if crypto_wallet_address:
        credentials_vault.set("payout_crypto_wallet", crypto_wallet_address, category="payout")
        saved.append("payout_crypto_wallet")
    if paypal_email:
        credentials_vault.set("payout_paypal_email", paypal_email, category="payout")
        saved.append("payout_paypal_email")
    credentials_vault.set("payout_preferred_method", preferred_payout_method, category="payout")
    saved.append("payout_preferred_method")

    return {
        "ok": True,
        "saved_keys": saved,
        "preferred_method": preferred_payout_method,
        "note": "These are stored encrypted in the vault. Stripe/Amazon/etc. still need to be configured separately in THEIR dashboards to actually send money here.",
    }


@tool(
    name="payouts.transfer_to_wallet",
    description="⚠️ REAL MONEY. Initiate a transfer from Stripe to your bank. Requires allow_real_payouts=true.",
    parameters={
        "type": "object",
        "properties": {
            "amount_usd": {"type": "number", "default": 0, "description": "0 = transfer all available balance."},
        },
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="payouts",
)
async def payouts_transfer_to_wallet(amount_usd: float = 0) -> Dict[str, Any]:
    if not getattr(settings, "allow_real_payouts", False):
        return {
            "ok": False,
            "error": "allow_real_payouts=false. Set ALLOW_REAL_PAYOUTS=true in .env to enable real money transfers.",
            "warning": "This moves REAL money. Gate is intentional.",
        }
    stripe_key = _cred("stripe_secret_key")
    if not stripe_key:
        return {"ok": False, "error": "stripe_secret_key not in vault"}
    try:
        import httpx
        # Stripe payouts are automatic by default (daily/weekly/monthly).
        # Manual payout via Payouts API:
        async with httpx.AsyncClient(timeout=15) as client:
            # Check balance first.
            bal_resp = await client.get("https://api.stripe.com/v1/balance", auth=(stripe_key, ""))
            if bal_resp.status_code != 200:
                return {"ok": False, "error": f"Stripe balance check failed: {bal_resp.status_code}"}
            available = bal_resp.json().get("available", [{}])[0].get("amount", 0) / 100
            if amount_usd == 0:
                amount_usd = available
            if amount_usd > available:
                return {"ok": False, "error": f"requested ${amount_usd} but only ${available} available"}
            # Initiate payout.
            payout_resp = await client.post(
                "https://api.stripe.com/v1/payouts",
                data={"amount": int(amount_usd * 100), "currency": "usd"},
                auth=(stripe_key, ""),
            )
        if payout_resp.status_code >= 400:
            return {"ok": False, "status": payout_resp.status_code, "error": payout_resp.text[:300]}
        data = payout_resp.json()
        return {
            "ok": True,
            "payout_id": data.get("id"),
            "amount_usd": amount_usd,
            "arrival_date": data.get("arrival_date"),
            "method": data.get("method"),
            "destination": data.get("destination"),
            "note": "Stripe will transfer this to your linked bank account within 1-2 business days.",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="payouts.revenue_history",
    description="Timeline of all revenue events (paid invoices + orders) over the last N days.",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 30},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="payouts",
)
async def payouts_revenue_history(days: int = 30) -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    events: List[Dict[str, Any]] = []
    try:
        inv = business_db.rows_to_dicts(business_db.query(
            "SELECT number, amount, currency, paid_at, client_id FROM invoices WHERE status = 'paid' AND paid_at >= ? ORDER BY paid_at DESC",
            (since,),
        ))
        for i in inv:
            events.append({"type": "invoice_paid", "amount": i["amount"], "currency": i["currency"], "date": i["paid_at"], "ref": i["number"]})
    except Exception:
        pass
    try:
        orders = business_db.rows_to_dicts(business_db.query(
            "SELECT id, total, currency, created_at FROM orders WHERE status IN ('paid', 'delivered') AND created_at >= ? ORDER BY created_at DESC",
            (since,),
        ))
        for o in orders:
            events.append({"type": "order_paid", "amount": o["total"], "currency": o["currency"], "date": o["created_at"], "ref": f"order #{o['id']}"})
    except Exception:
        pass
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    total_usd = sum(e["amount"] for e in events if e.get("currency") == "USD")
    total_jod = sum(e["amount"] for e in events if e.get("currency") == "JOD")
    return {
        "ok": True,
        "days": days,
        "events": events[:100],
        "total_usd": round(total_usd, 2),
        "total_jod": round(total_jod, 2),
        "event_count": len(events),
    }


PLUGIN_NAME = "payouts"
PLUGIN_VERSION = "2.0.0"
PLUGIN_DESCRIPTION = "Money flow: track all revenue, auto-forward to Zain Cash, budget-aware transfers."


# --------------------------------------------------------------------
# Phase 15: Zain Cash integration
# --------------------------------------------------------------------

@tool(
    name="payouts.setup_zain_cash",
    description="Configure Zain Cash as Sir's primary e-wallet destination. All revenue forwarding will go here.",
    parameters={
        "type": "object",
        "properties": {
            "zain_cash_phone": {"type": "string", "description": "Your Zain Cash registered phone number (9627XXXXXXXX format)."},
            "zain_cash_merchant_id": {"type": "string", "default": "", "description": "If you have a merchant account for API access."},
        },
        "required": ["zain_cash_phone"],
    },
    risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    category="payouts",
)
async def payouts_setup_zain_cash(zain_cash_phone: str, zain_cash_merchant_id: str = "") -> Dict[str, Any]:
    from backend.services.credentials_vault import credentials_vault
    credentials_vault.set("zain_cash_phone", zain_cash_phone, category="payout")
    if zain_cash_merchant_id:
        credentials_vault.set("zain_cash_merchant_id", zain_cash_merchant_id, category="payout")
    credentials_vault.set("payout_preferred_method", "zain_cash", category="payout")
    return {
        "ok": True,
        "phone": zain_cash_phone,
        "preferred_method": "zain_cash",
        "message": (
            "Zain Cash configured as your primary payout destination. "
            "When money lands in Stripe/Lemon Squeezy, JARVIS will: "
            "(1) notify you, (2) guide you through the transfer to Zain Cash, "
            "(3) optionally auto-trigger if Zain Cash merchant API is configured."
        ),
        "note": "Zain Cash doesn't have a public P2P API for individuals. JARVIS can use your bank app → Zain Cash, or the Zain Cash merchant API if configured.",
    }


@tool(
    name="payouts.auto_forward_to_zain_cash",
    description="When revenue lands in Stripe/Lemon Squeezy, JARVIS guides the money to Zain Cash. Returns step-by-step instructions for the full chain.",
    parameters={
        "type": "object",
        "properties": {
            "amount_usd": {"type": "number", "default": 0, "description": "0 = all available."},
            "source": {"type": "string", "default": "auto", "enum": ["auto", "stripe", "lemonsqueezy"], "description": "Which processor to pull from."},
        },
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="payouts",
)
async def payouts_auto_forward_to_zain_cash(amount_usd: float = 0, source: str = "auto") -> Dict[str, Any]:
    from backend.services.credentials_vault import credentials_vault
    zc_phone = credentials_vault.get("zain_cash_phone")
    if not zc_phone:
        return {
            "ok": False,
            "error": "Zain Cash not configured. Call payouts.setup_zain_cash first.",
        }

    # Check budget.
    from plugins.budget.plugin import budget_check, budget_record_spend
    budget = await budget_check()
    if not budget.get("within_budget", True):
        return {"ok": False, "blocked": True, "reason": "Budget cap reached.", "budget": budget}

    # The money chain for Jordan:
    # Lemon Squeezy / Stripe → Payoneer → Jordan bank → Zain Cash
    # OR local: direct Zain Cash merchant payment

    chain = [
        {"step": 1, "action": "Check balance at payment processor", "tool": f"payouts.track_all (source={source})"},
        {"step": 2, "action": "Trigger payout from processor to your bank/Payoneer", "tool": "payouts.transfer_to_wallet OR lemonsqueezy auto-payout (monthly 11-15th)"},
        {"step": 3, "action": "Wait for bank to receive (1-3 business days for Stripe, monthly for Lemon Squeezy)", "timing": "1-5 days"},
        {"step": 4, "action": f"Open your banking app → transfer to Zain Cash ({zc_phone})", "manual": True, "timing": "instant via CliQ"},
        {"step": 5, "action": "Money arrives in your Zain Cash wallet", "done": True},
    ]

    # If source is Stripe and real payouts enabled, actually trigger it.
    triggered = False
    if source in ("auto", "stripe"):
        stripe_key = _cred("stripe_secret_key")
        if stripe_key and getattr(settings, "allow_real_payouts", False):
            transfer = await payouts_transfer_to_wallet(amount_usd=amount_usd)
            triggered = transfer.get("ok", False)
            if triggered:
                # Record the spend against budget (transfer fee if any).
                await budget_record_spend(amount_usd=0, category="payout_transfer", description=f"Stripe payout of ${amount_usd}")

    return {
        "ok": True,
        "zain_cash_phone": zc_phone,
        "amount_usd": amount_usd,
        "source": source,
        "stripe_transfer_triggered": triggered,
        "money_chain": chain,
        "estimated_time": "3-7 business days end-to-end (processor → bank → Zain Cash)",
        "note": "Zain Cash doesn't have a public P2P API yet. The final bank→Zain Cash step requires your banking app. JARVIS guides you through each step.",
    }


# --------------------------------------------------------------------
# Phase 15: Account setup guide (Jordan-specific)
# --------------------------------------------------------------------

@tool(
    name="payouts.setup_accounts_jordan",
    description="Step-by-step guide for setting up ALL payment accounts from Jordan. JARVIS can't create them automatically (they need your ID) but guides you through every step.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="payouts",
)
async def payouts_setup_accounts_jordan() -> Dict[str, Any]:
    return {
        "ok": True,
        "country": "Jordan",
        "note": "JARVIS CANNOT create these accounts for you (they need your passport/ID verification). But here's the exact order to set them up:",
        "accounts": [
            {
                "name": "Zain Cash (YOUR WALFLOW)",
                "priority": "1 — DO THIS FIRST",
                "url": "Download Zain Cash app from App Store / Google Play",
                "steps": ["Download app", "Register with your Zain phone number", "Verify your ID at a Zain shop", "You now have a wallet that can send/receive money"],
                "takes": "1-2 hours (ID verification needs shop visit)",
            },
            {
                "name": "Payoneer (YOUR INTERNATIONAL BRIDGE)",
                "priority": "2 — CRITICAL",
                "url": "https://payoneer.com",
                "why": "Gives you a US/EU virtual bank account. Lemon Squeezy, Stripe, Amazon all pay out to Payoneer. Payoneer then sends to your Jordan bank.",
                "steps": ["Sign up at payoneer.com", "Verify with Jordanian passport/ID + bank statement", "Get your US account details (routing + account number)", "Put those details into Lemon Squeezy + Amazon Associates"],
                "takes": "3-5 business days for approval",
                "jordan_status": "WORKS — Payoneer officially supports Jordan",
            },
            {
                "name": "Lemon Squeezy (YOUR PAYMENT PROCESSOR)",
                "priority": "3 — HOW YOU GET PAID",
                "url": "https://lemonsqueezy.com/signup",
                "why": "Merchant of Record — handles credit cards globally, calculates VAT, pays you out monthly. Perfect for Jordan (Stripe doesn't support JO).",
                "steps": ["Sign up", "Verify email", "Add business details", "Connect Payoneer as payout method", "Generate API key", "Put 'lemonsqueezy_api_key' in JARVIS vault"],
                "takes": "1 day",
                "jordan_status": "WORKS — Lemon Squeezy accepts Jordan creators",
            },
            {
                "name": "Amazon Associates (AFFILIATE INCOME)",
                "priority": "4 — AFFILIATE",
                "url": "https://affiliate-program.amazon.com",
                "steps": ["Sign up", "Add Payoneer bank details", "Generate 3 qualifying sales within 180 days", "Get approved", "Put PA-API keys in vault"],
                "takes": "1-6 months (needs qualifying sales)",
                "jordan_status": "WORKS — Jordan is supported",
            },
            {
                "name": "YouTube + AdSense (VIDEO INCOME)",
                "priority": "5 — VIDEO",
                "url": "https://studio.youtube.com → Monetization",
                "steps": ["Create YouTube channel", "Reach 1,000 subs + 4,000 watch hours", "Apply for monetization", "Link AdSense (needs Payoneer bank)", "Get paid monthly ($100 min)"],
                "takes": "3-12 months",
                "jordan_status": "WORKS — Jordan is supported for AdSense",
            },
            {
                "name": "CliQ (INSTANT LOCAL TRANSFERS)",
                "priority": "6 — LOCAL BANKING",
                "url": "Your Jordan bank app (Arab Bank, Cairo Amman Bank, etc.)",
                "why": "CliQ lets you send money instantly between Jordanian banks AND to Zain Cash. This is the final link: bank → Zain Cash.",
                "steps": ["Activate CliQ in your banking app", "Link your Zain Cash number as a beneficiary", "Transfer is instant + free"],
                "takes": "10 minutes",
                "jordan_status": "WORKS — CliQ is Jordan's national instant payment system",
            },
        ],
        "money_flow_summary": (
            "Customer pays → Lemon Squeezy (global cards) → Payoneer (your virtual US account) → "
            "Your Jordan bank (automatically monthly) → CliQ transfer → Zain Cash (instant)"
        ),
        "what_jarvis_can_do": (
            "JARVIS can: create products on Lemon Squeezy, generate checkout links, track sales, "
            "notify you when payouts arrive, guide you through each transfer step. "
            "JARVIS CANNOT: create accounts for you (needs your passport), "
            "or directly push to Zain Cash (no public API for P2P)."
        ),
    }
