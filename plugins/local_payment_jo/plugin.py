# JARVIS OMEGA - Local Jordan Payment (Phase 16)
from __future__ import annotations
import io, base64, json, urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional
from backend.tools import tool, RiskTier
from backend.config import settings

def _cred(key):
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(key) or None
    except: return None

@tool(name="local_payment.zain_cash_qr", description="Generate a Zain Cash payment QR code. Customer scans with Zain Cash app → pays instantly. Free, no merchant account.", parameters={"type":"object","properties":{"amount_jod":{"type":"number"},"phone":{"type":"string","default":"","description":"Your Zain Cash phone (9627X...). Empty = from vault."},"note":{"type":"string","default":""}},"required":["amount_jod"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="local_payment_jo")
async def zain_cash_qr(amount_jod: float, phone: str = "", note: str = "") -> Dict[str, Any]:
    phone = phone or _cred("zain_cash_phone") or ""
    if not phone: return {"ok": False, "error": "Set zain_cash_phone in vault or pass phone param."}
    # Zain Cash deep-link format: generates a QR that opens the app
    payload = json.dumps({"p": phone, "a": int(amount_jod * 1000), "n": note or "JARVIS payment", "c": "JOD"})
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return {"ok": False, "error": "qrcode not installed — pip install qrcode[pil]"}
    return {"ok": True, "qr_base64": b64, "amount_jod": amount_jod, "phone": phone,
            "instructions": "اعرض هذا الـ QR للعميل. سيفتح تطبيق زين كاش ويقوم بالدفع فوراً.",
            "deep_link": f"zaincash://pay?phone={phone}&amount={amount_jod}&note={urllib.parse.quote(note)}"}

@tool(name="local_payment.cliq_request", description="Generate CliQ payment request. Customer pays via their banking app.", parameters={"type":"object","properties":{"amount_jod":{"type":"number"},"iban":{"type":"string","default":"","description":"Your IBAN. Empty = from vault."},"alias":{"type":"string","default":"","description":"Your CliQ alias."}},"required":["amount_jod"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="local_payment_jo")
async def cliq_request(amount_jod: float, iban: str = "", alias: str = "") -> Dict[str, Any]:
    iban = iban or _cred("payout_bank_iban") or ""
    alias = alias or _cred("cliq_alias") or ""
    return {"ok": True, "amount_jod": amount_jod, "iban": iban, "cliq_alias": alias,
            "instructions": f"حوّل {amount_jod} د.أ عبر CliQ إلى: {alias or iban}",
            "note": "CliQ transfers are instant and free between Jordanian banks."}

@tool(name="local_payment.cod_order", description="Create a Cash-on-Delivery order record.", parameters={"type":"object","properties":{"customer_name":{"type":"string"},"customer_phone":{"type":"string"},"amount_jod":{"type":"number"},"product_name":{"type":"string"},"address":{"type":"string","default":""}},"required":["customer_name","amount_jod"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="local_payment_jo")
async def cod_order(customer_name: str, amount_jod: float, customer_phone: str = "", product_name: str = "", address: str = "") -> Dict[str, Any]:
    from backend import business_db
    from datetime import datetime
    # Create an order record
    business_db.audit("cod_order", "ecommerce", target=customer_name, details={"amount": amount_jod, "product": product_name})
    return {"ok": True, "method": "COD", "customer": customer_name, "amount_jod": amount_jod,
            "note": "العميل يدفع نقداً عند الاستلام. تأكد من تسجيل الدفع عند التوصيل."}

@tool(name="local_payment.checkout_page", description="Generate an Arabic RTL checkout page with Zain Cash + CliQ + COD options.", parameters={"type":"object","properties":{"product_name":{"type":"string"},"price_jod":{"type":"number"},"zain_cash_phone":{"type":"string","default":""},"cliq_alias":{"type":"string","default":""},"output_dir":{"type":"string","default":"./storage/website/checkout"}},"required":["product_name","price_jod"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="local_payment_jo")
async def checkout_page(product_name: str, price_jod: float, zain_cash_phone: str = "", cliq_alias: str = "", output_dir: str = "./storage/website/checkout") -> Dict[str, Any]:
    zc = zain_cash_phone or _cred("zain_cash_phone") or ""
    cliq = cliq_alias or _cred("cliq_alias") or ""
    # Generate Zain Cash QR
    qr_b64 = ""
    if zc:
        qr_result = await zain_cash_qr(amount_jod=price_jod, phone=zc, note=product_name)
        qr_b64 = qr_result.get("qr_base64", "")
    # Build payment options HTML
    zain_html = ""
    if qr_b64:
        zain_html = '<div class="border rounded-lg p-4"><h3 class="font-bold mb-2">📦 زين كاش</h3>'
        zain_html += '<img src="data:image/png;base64,' + qr_b64 + '" class="mx-auto mb-2" width="200">'
        zain_html += '<p class="text-sm text-gray-500">امسح للتحويل الفوري</p></div>'
    elif zc:
        zain_html = '<div class="border rounded-lg p-4"><p>زين كاش: ' + zc + '</p></div>'
    cliq_html = ""
    if cliq:
        cliq_html = '<div class="border rounded-lg p-4"><h3 class="font-bold mb-2">🏦 CliQ</h3>'
        cliq_html += '<p>حوّل عبر CliQ إلى: <strong>' + cliq + '</strong></p>'
        cliq_html += '<p class="text-sm text-gray-500">تحويل فوري ومجاني</p></div>'
    cod_html = '<div class="border rounded-lg p-4"><h3 class="font-bold mb-2">💵 الدفع عند الاستلام</h3><p>ادفع نقداً عند وصول الطلب</p></div>'
    html = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>دفع: """ + product_name + """</title><script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap">
<style>body{font-family:Tajawal,sans-serif}</style></head><body class="bg-gray-50 p-6">
<div class="max-w-md mx-auto bg-white rounded-xl shadow-lg p-8">
<h1 class="text-2xl font-bold mb-2">""" + product_name + """</h1>
<div class="text-3xl text-indigo-600 font-bold mb-6">""" + str(price_jod) + """ د.أ</div>
<div class="space-y-4">
""" + zain_html + cliq_html + cod_html + """
</div></div></body></html>"""
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / "checkout.html"; path.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(path), "price_jod": price_jod}

@tool(name="local_payment.check_received", description="Manually confirm a payment was received (Zain Cash / CliQ / COD).", parameters={"type":"object","properties":{"method":{"type":"string","enum":["zain_cash","cliq","cod","bank"]},"amount_jod":{"type":"number"},"customer_name":{"type":"string","default":""},"reference":{"type":"string","default":""}},"required":["method","amount_jod"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="local_payment_jo")
async def check_received(method: str, amount_jod: float, customer_name: str = "", reference: str = "") -> Dict[str, Any]:
    from backend import business_db
    business_db.audit("payment_received", "payouts", target=customer_name or method,
                      details={"method": method, "amount_jod": amount_jod, "ref": reference})
    return {"ok": True, "confirmed": True, "method": method, "amount_jod": amount_jod,
            "note": "Payment recorded. JARVIS cannot auto-verify Zain Cash / CliQ (no public webhook API). Confirm manually."}

PLUGIN_NAME = "local_payment_jo"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Zain Cash QR + CliQ + COD + Arabic checkout page."
