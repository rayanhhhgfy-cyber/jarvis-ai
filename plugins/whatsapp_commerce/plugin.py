# JARVIS OMEGA - WhatsApp Commerce (Phase 16)
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="wacom.menu_card", description="Generate a WhatsApp-ready text menu card for products.", parameters={"type":"object","properties":{"products":{"type":"array","items":{"type":"object"},"description":"[{name, price_jod, description}]"},"business_name":{"type":"string"}},"required":["products"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="whatsapp_commerce")
async def menu_card(products: List[Dict], business_name: str = "JARVIS Store") -> Dict[str, Any]:
    lines = [f"🏪 *{business_name}*\n📋 القائمة:\n"]
    for i, p in enumerate(products, 1):
        lines.append(f"\n{i}. *{p.get('name','?')}* — {p.get('price_jod',0)} د.أ")
        if p.get("description"): lines.append(f"   {p['description'][:80]}")
    lines.append("\n\n📩 أرسل رقم المنتج للطلب!")
    return {"ok": True, "menu_text": "\n".join(lines)}

@tool(name="wacom.take_order", description="Parse a WhatsApp message into a structured order. LLM extracts product + quantity.", parameters={"type":"object","properties":{"message":{"type":"string"},"products":{"type":"array","items":{"type":"object"},"default":[]}},"required":["message"]}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="whatsapp_commerce")
async def take_order(message: str, products: Optional[List[Dict]] = None) -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    products = products or []
    try:
        reply = await llm_service.get_response(
            user_message=f"Customer message: {message}\nAvailable products: {json.dumps(products[:20], ensure_ascii=False)}",
            system_instructions="Extract order details. Output STRICT JSON: {\"items\":[{\"name\":string,\"quantity\":int}],\"customer_name\":string,\"notes\":string,\"total_estimated_jod\":number}. If unclear, set items=[].",
            inject_memory=False)
        text = reply.strip().lstrip("`").rstrip("`")
        if text.startswith("json"): text = text[4:]
        parsed = json.loads(text)
        return {"ok": True, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@tool(name="wacom.send_payment_request", description="Generate Zain Cash QR + CliQ payment request for an order and format as WhatsApp message.", parameters={"type":"object","properties":{"amount_jod":{"type":"number"},"product_name":{"type":"string","default":""},"customer_phone":{"type":"string","default":""}},"required":["amount_jod"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="whatsapp_commerce")
async def send_payment_request(amount_jod: float, product_name: str = "", customer_phone: str = "") -> Dict[str, Any]:
    from plugins.local_payment_jo.plugin import zain_cash_qr
    qr = await zain_cash_qr(amount_jod=amount_jod, note=product_name)
    whatsapp_msg = f"💰 المبلغ المطلوب: *{amount_jod} د.أ*\n\n📦 امسح رمز QR أدناه لتطبيق زين كاش للدفع الفوري:\n\nأو حوّل عبر CliQ."
    return {"ok": True, "payment_message": whatsapp_msg, "qr_base64": qr.get("qr_base64",""), "amount_jod": amount_jod}

@tool(name="wacom.confirm_order", description="Generate an Arabic order confirmation message for WhatsApp.", parameters={"type":"object","properties":{"order_id":{"type":"string"},"items":{"type":"array","items":{"type":"object"},"default":[]},"total_jod":{"type":"number"},"delivery_eta":{"type":"string","default":""}},"required":["total_jod"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="whatsapp_commerce")
async def confirm_order(total_jod: float, order_id: str = "", items: Optional[List[Dict]] = None, delivery_eta: str = "") -> Dict[str, Any]:
    items = items or []
    lines = [f"✅ تم تأكيد طلبك!", f"📦 رقم الطلب: {order_id or 'N/A'}"]
    for i in items: lines.append(f"• {i.get('name','?')} ×{i.get('quantity',1)}")
    lines.append(f"\n💰 الإجمالي: *{total_jod} د.أ*")
    if delivery_eta: lines.append(f"\n🚚 التوصيل المتوقع: {delivery_eta}")
    lines.append("\nشكراً لثقتك بنا! 🌟")
    return {"ok": True, "confirmation_text": "\n".join(lines)}

@tool(name="wacom.order_status", description="Generate Arabic order status update for WhatsApp.", parameters={"type":"object","properties":{"order_id":{"type":"string"},"status":{"type":"string","enum":["confirmed","preparing","shipped","delivered"]}},"required":["status"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="whatsapp_commerce")
async def order_status(order_id: str = "", status: str = "confirmed") -> Dict[str, Any]:
    msgs = {"confirmed":"✅ تم تأكيد طلبك! نبدأ بالتجهيز الآن.","preparing":"⏳ طلبك قيد التجهيز...","shipped":"🚚 تم شحن طلبك! سيصلك قريباً.","delivered":"📦 تم توصيل طلبك! نتمنى أن يعجبك. شاركنا رأيك 🌟"}
    return {"ok": True, "status_message": msgs.get(status, "حالة الطلب: " + status)}

@tool(name="wacom.catalog_upload", description="Generate a WhatsApp Business catalog JSON from product list.", parameters={"type":"object","properties":{"products":{"type":"array","items":{"type":"object"}}},"required":["products"]}, risk_tier=RiskTier.TIER_0_OBSERVE, category="whatsapp_commerce")
async def catalog_upload(products: List[Dict]) -> Dict[str, Any]:
    catalog = [{"id": str(i+1), "name": p.get("name",""), "price": f"{p.get('price_jod',0)} JOD", "description": p.get("description",""), "url": p.get("image_url","")} for i, p in enumerate(products)]
    return {"ok": True, "catalog": catalog, "count": len(catalog), "note": "Upload this via WhatsApp Business app → Catalog → Add products."}

PLUGIN_NAME = "whatsapp_commerce"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "WhatsApp commerce: menu, order taking, Zain Cash payment, confirmation, status updates."
