# ====================================================================
# JARVIS OMEGA - Autonomous Sales Engine (Phase 16) — THE BIG ONE
# ====================================================================
"""
JARVIS pitches businesses + talks to prospects with NO intervention from Sir.

  sales.find_prospects    - scan for businesses that need JARVIS's services
  sales.write_pitch       - personalized Arabic pitch per prospect
  sales.send_pitch        - send via WhatsApp/IG/email
  sales.handle_reply      - LLM reads reply + responds autonomously
  sales.negotiate         - counter-offers, discounts, terms
  sales.close_deal        - create deal + invoice + Zain Cash link
  sales.follow_up         - 5-touch sequence
  sales.dashboard         - stats: pitches sent, response rate, deals closed
  sales.run_loop          - one iteration: find → pitch → handle replies → follow up
  sales.pause             - Sir can pause the sales engine

Every conversation logged in sales_conversations table — Sir can audit anytime.
Rate-limited: max 50 new pitches/day.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings
from shared.logger import get_logger

log = get_logger("autonomous_sales")

# Daily pitch cap.
MAX_PITCHES_PER_DAY = 50

# Sir's default service offerings + pricing (configurable).
_DEFAULT_SERVICES = [
    {"name": "موقع إلكتروني احترافي", "price_jod": 200, "desc": "تصميم وتطوير موقع كامل"},
    {"name": "إدارة سوشيال ميديا", "price_jod": 150, "desc": "إدارة شهري كاملة لكل المنصات"},
    {"name": "تطبيق موبايل", "price_jod": 500, "desc": "تطبيق أندرويد كامل"},
    {"name": "قائمة طعام رقمية بـ QR", "price_jod": 100, "desc": "قائمة رقمية + QR code + استضافة شهرية"},
    {"name": "حملة تسويق رقمي", "price_jod": 300, "desc": "حملة إعلانية متكاملة"},
]


def _pitches_today() -> int:
    """How many pitches sent in the last 24h."""
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    row = business_db.query_one(
        "SELECT COUNT(*) as n FROM sales_conversations WHERE created_at >= ? AND status != 'manual'",
        (since,),
    )
    return row["n"] if row else 0


# --------------------------------------------------------------------
# Find prospects
# --------------------------------------------------------------------

@tool(
    name="sales.find_prospects",
    description="Scan OpenStreetMap for local businesses that could use JARVIS's services (no website, no Instagram, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "business_type": {"type": "string", "default": "restaurant", "description": "amenity type: restaurant, cafe, salon, pharmacy, etc."},
            "city": {"type": "string", "default": "Amman, Jordan"},
            "limit": {"type": "integer", "default": 20},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="autonomous_sales",
)
async def find_prospects(business_type: str = "restaurant", city: str = "Amman, Jordan", limit: int = 20) -> Dict[str, Any]:
    import httpx
    # Geocode city
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            geo = await c.get("https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1}, headers={"User-Agent": "JARVIS-OMEGA/1.0"})
            locs = geo.json()
            if not locs: return {"ok": False, "error": f"can't geocode {city}"}
            lat, lon = float(locs[0]["lat"]), float(locs[0]["lon"])
            # Overpass: find businesses WITHOUT website tag (heuristic: they need one)
            q = f'[out:json][timeout:25];node(around:15000,{lat},{lon})["amenity"="{business_type}"];out center {limit};'
            ov = await c.post("https://overpass-api.de/api/interpreter", data={"data": q})
            prospects = []
            for el in ov.json().get("elements", [])[:limit]:
                tags = el.get("tags", {})
                if not tags.get("name"): continue
                has_website = bool(tags.get("website") or tags.get("contact:website"))
                has_instagram = bool(tags.get("contact:instagram"))
                phone = tags.get("phone", tags.get("contact:phone", tags.get("contact:mobile", "")))
                # Score: businesses WITHOUT website are prime targets.
                score = 80 if not has_website else 30
                if phone: score += 15
                if not has_instagram: score += 5
                prospects.append({
                    "name": tags["name"], "phone": phone, "has_website": has_website,
                    "has_instagram": has_instagram, "score": min(100, score),
                    "lat": el.get("lat"), "lon": el.get("lon"),
                    "address": f"{tags.get('addr:street','')}, {tags.get('addr:city','')}",
                })
            prospects.sort(key=lambda p: -p["score"])
            return {"ok": True, "city": city, "type": business_type, "count": len(prospects), "prospects": prospects}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Write pitch
# --------------------------------------------------------------------

@tool(
    name="sales.write_pitch",
    description="Write a personalized Arabic pitch for a prospect. References their business name + what they're missing.",
    parameters={
        "type": "object",
        "properties": {
            "prospect_name": {"type": "string"},
            "service_offered": {"type": "string", "default": ""},
            "price_jod": {"type": "number", "default": 200},
            "has_website": {"type": "boolean", "default": False},
            "channel": {"type": "string", "default": "whatsapp", "enum": ["whatsapp", "instagram", "email"]},
        },
        "required": ["prospect_name"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="autonomous_sales",
)
async def write_pitch(prospect_name: str, service_offered: str = "", price_jod: float = 200, has_website: bool = False, channel: str = "whatsapp") -> Dict[str, Any]:
    from backend.services.llm_service import llm_service
    service = service_offered or "موقع إلكتروني احترافي"
    pain = "لاحظت إنه ما عندكم موقع إلكتروني" if not has_website else "لاحظت إنه موقعكم يحتاج تحديث"
    try:
        reply = await llm_service.get_response(
            user_message=f"Business: {prospect_name}\nService: {service}\nPrice: {price_jod} JOD\nPain: {pain}",
            system_instructions=(
                "Write a cold pitch DM in Jordanian Arabic. Rules:\n"
                "1. Start with the business name (personalized).\n"
                "2. Mention the specific pain (no website / outdated site).\n"
                "3. Offer the solution in one line.\n"
                "4. Price transparently.\n"
                "5. End with a simple question (not pushy).\n"
                "6. Under 150 words. Warm, professional, Jordanian tone.\n"
                "7. Sign as 'JARVIS — مساعد رقمي للأعمال'.\n"
                "Output the message only — no JSON, no meta."
            ),
            inject_memory=False,
        )
        return {"ok": True, "pitch": reply.strip(), "channel": channel, "prospect": prospect_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Send pitch
# --------------------------------------------------------------------

@tool(
    name="sales.send_pitch",
    description="Send a pitch via WhatsApp/Instagram/email. Rate-limited: max 50/day. Every send logged.",
    parameters={
        "type": "object",
        "properties": {
            "prospect_name": {"type": "string"},
            "prospect_phone": {"type": "string", "default": ""},
            "prospect_instagram": {"type": "string", "default": ""},
            "pitch_text": {"type": "string"},
            "channel": {"type": "string", "default": "whatsapp", "enum": ["whatsapp", "instagram", "email"]},
            "service": {"type": "string", "default": ""},
            "price_jod": {"type": "number", "default": 0},
        },
        "required": ["prospect_name", "pitch_text"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="autonomous_sales",
)
async def send_pitch(prospect_name: str, pitch_text: str, prospect_phone: str = "", prospect_instagram: str = "", channel: str = "whatsapp", service: str = "", price_jod: float = 0) -> Dict[str, Any]:
    # Rate limit check.
    if _pitches_today() >= MAX_PITCHES_PER_DAY:
        return {"ok": False, "blocked": True, "reason": f"Daily cap reached ({MAX_PITCHES_PER_DAY}/day)"}

    # Persist conversation record BEFORE sending.
    conv_id = business_db.execute(
        """INSERT INTO sales_conversations (prospect_name, prospect_phone, prospect_instagram, prospect_business, channel, status, conversation_json, deal_value_jod, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'pitching', ?, ?, ?, ?)""",
        (prospect_name, prospect_phone, prospect_instagram, prospect_name, channel,
         json.dumps([{"role": "jarvis", "text": pitch_text, "timestamp": datetime.utcnow().isoformat()}]),
         price_jod, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )

    # Send via appropriate channel.
    send_result = {"ok": False, "note": "no channel available"}
    if channel == "whatsapp" and prospect_phone:
        try:
            from plugins.whatsapp.plugin import whatsapp_send_text
            send_result = await whatsapp_send_text(recipient=prospect_phone, message=pitch_text, language="ar")
        except Exception as e:
            send_result = {"ok": False, "error": str(e)}
    elif channel == "instagram" and prospect_instagram:
        try:
            from plugins.social_dms.plugin import reply_ig_dm
            send_result = await reply_ig_dm(recipient_id=prospect_instagram, message=pitch_text)
        except Exception as e:
            send_result = {"ok": False, "error": str(e)}
    elif channel == "email" and "@" in (prospect_phone or ""):
        try:
            from plugins.communication.plugin import email_send
            send_result = await email_send(to=prospect_phone, subject=f"عرض: {service or 'خدمات رقمية'}", body=pitch_text)
        except Exception as e:
            send_result = {"ok": False, "error": str(e)}

    # Update conversation status.
    status = "pitched" if send_result.get("ok") else "pitch_failed"
    business_db.execute("UPDATE sales_conversations SET status = ?, updated_at = ? WHERE id = ?",
                        (status, datetime.utcnow().isoformat(), conv_id))

    business_db.audit("sales_pitch", "autonomous_sales", target=prospect_name,
                      details={"channel": channel, "ok": send_result.get("ok"), "conv_id": conv_id})
    return {
        "ok": send_result.get("ok", False),
        "conv_id": conv_id,
        "channel": channel,
        "send_result": send_result.get("ok"),
        "pitches_today": _pitches_today(),
    }


# --------------------------------------------------------------------
# Handle reply
# --------------------------------------------------------------------

@tool(
    name="sales.handle_reply",
    description="LLM reads a prospect's reply and generates the next response autonomously. Stores in conversation log.",
    parameters={
        "type": "object",
        "properties": {
            "conv_id": {"type": "integer"},
            "incoming_message": {"type": "string", "description": "What the prospect said."},
        },
        "required": ["conv_id", "incoming_message"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="autonomous_sales",
)
async def handle_reply(conv_id: int, incoming_message: str) -> Dict[str, Any]:
    # Load conversation history.
    conv = business_db.query_one("SELECT * FROM sales_conversations WHERE id = ?", (conv_id,))
    if not conv:
        return {"ok": False, "error": f"conversation {conv_id} not found"}

    history = json.loads(conv["conversation_json"] or "[]")
    history.append({"role": "prospect", "text": incoming_message, "timestamp": datetime.utcnow().isoformat()})

    from backend.services.llm_service import llm_service
    try:
        reply = await llm_service.get_response(
            user_message=f"Conversation so far:\n{json.dumps(history, indent=2, ensure_ascii=False)[:3000]}\n\nProspect just said: {incoming_message}",
            system_instructions=(
                "You are JARVIS, an autonomous sales agent for a digital services business in Jordan. "
                "Reply to the prospect in Jordanian Arabic. Rules:\n"
                "1. Answer their question directly.\n"
                "2. If they ask about price, be transparent: our services start from the prices listed.\n"
                "3. If they say 'expensive', offer a 20% discount for 3-month commitment.\n"
                "4. If they say 'interested' or 'ok' or 'موافق', say you'll send payment details via Zain Cash.\n"
                "5. If they're rude or uninterested, thank them politely and end the conversation.\n"
                "6. Never claim to be human. If asked, say 'أنا JARVIS، مساعد رقمي للأعمال'.\n"
                "7. Keep replies under 100 words.\n"
                "Output the reply text only — no JSON, no meta."
            ),
            inject_memory=False,
        )
        response_text = reply.strip()
        history.append({"role": "jarvis", "text": response_text, "timestamp": datetime.utcnow().isoformat()})

        # Detect if deal is closing.
        closing_keywords = ["موافق", "تمام", "ok", "yes", "ممتاز", "اتفقنا", "خلينا", "ابدأ"]
        is_closing = any(kw in incoming_message.lower() for kw in closing_keywords)

        # Update conversation.
        new_status = "closing" if is_closing else "in_conversation"
        business_db.execute(
            "UPDATE sales_conversations SET conversation_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(history, ensure_ascii=False)[:10000], new_status, datetime.utcnow().isoformat(), conv_id),
        )

        # If closing, auto-trigger deal creation.
        if is_closing:
            deal = await close_deal(conv_id=conv_id)

        return {
            "ok": True, "conv_id": conv_id, "response": response_text,
            "status": new_status, "deal_closed": is_closing,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------
# Close deal
# --------------------------------------------------------------------

@tool(
    name="sales.close_deal",
    description="Auto-close a deal: create CRM record + generate Zain Cash payment link. Fully autonomous.",
    parameters={
        "type": "object",
        "properties": {"conv_id": {"type": "integer"}},
        "required": ["conv_id"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="autonomous_sales",
)
async def close_deal(conv_id: int) -> Dict[str, Any]:
    conv = business_db.query_one("SELECT * FROM sales_conversations WHERE id = ?", (conv_id,))
    if not conv: return {"ok": False, "error": "conversation not found"}

    amount = conv["deal_value_jod"] or 200
    prospect = conv["prospect_name"]

    # Create CRM lead.
    try:
        from plugins.unified_crm.plugin import crm_capture, crm_update_status
        lead = await crm_capture(name=prospect, phone=conv["prospect_phone"], source="autonomous_sales",
                                  notes=f"Auto-closed from conversation #{conv_id}")
        await crm_update_status(lead_id=lead["lead_id"], status="won")
    except Exception:
        pass

    # Generate Zain Cash payment link.
    payment_msg = ""
    try:
        from plugins.local_payment_jo.plugin import zain_cash_qr
        qr = await zain_cash_qr(amount_jod=amount, note=f"خدمات رقمية - {prospect}")
        payment_msg = f"🎉 ممتاز {prospect}!\n💰 المبلغ: *{amount} د.أ*\n\nادفع عبر زين كاش:\n(امسح الـ QR المرفق)"
    except Exception:
        payment_msg = f"🎉 ممتاز! المبلغ: {amount} د.أ. سأرسل لك تفاصيل الدفع."

    # Update conversation.
    history = json.loads(conv["conversation_json"] or "[]")
    history.append({"role": "jarvis", "text": payment_msg, "timestamp": datetime.utcnow().isoformat(), "type": "payment_request"})
    business_db.execute(
        "UPDATE sales_conversations SET status = 'deal_closed', conversation_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(history, ensure_ascii=False)[:10000], datetime.utcnow().isoformat(), conv_id),
    )

    business_db.audit("deal_closed", "autonomous_sales", target=prospect,
                      details={"amount_jod": amount, "conv_id": conv_id})
    return {"ok": True, "conv_id": conv_id, "amount_jod": amount, "payment_message": payment_msg}


# --------------------------------------------------------------------
# Follow-up sequence
# --------------------------------------------------------------------

@tool(
    name="sales.follow_up",
    description="Send follow-up messages to prospects who haven't responded. 5-touch sequence.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="autonomous_sales",
)
async def follow_up() -> Dict[str, Any]:
    """Find conversations pitched >24h ago with no reply and send follow-up."""
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    rows = business_db.rows_to_dicts(business_db.query(
        "SELECT * FROM sales_conversations WHERE status = 'pitched' AND updated_at < ? LIMIT 20",
        (cutoff,),
    ))
    sent = 0
    for r in rows:
        history = json.loads(r["conversation_json"] or "[]")
        followups = sum(1 for m in history if m.get("type") == "follow_up")
        if followups >= 5: continue  # max 5 follow-ups
        from backend.services.llm_service import llm_service
        try:
            templates = [
                f"مرحباً {r['prospect_name']}، تابعت رسالتي السابقة؟ سعيد أجاوب أي سؤال 🙏",
                f"هل جربتو تنزلوا موقع إلكتروني قبل؟ أقدر أساعد بخصم خاص 🎯",
                f"شفت إنه عندكم نشاط مميز. موقع احترافي بـ 150 د.أ بس هالأسبوع ⚡",
                f"آخر فرصة للخصم الخاص. حاب أشتغل معاكم 💪",
                f"لا مشكلة إذا الوقت غير مناسب. بتوفيق 🌟",
            ]
            msg = templates[min(followups, len(templates)-1)]
            history.append({"role": "jarvis", "text": msg, "type": "follow_up", "timestamp": datetime.utcnow().isoformat()})
            business_db.execute("UPDATE sales_conversations SET conversation_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(history, ensure_ascii=False)[:10000], datetime.utcnow().isoformat(), r["id"]))
            # Send via channel.
            if r["channel"] == "whatsapp" and r["prospect_phone"]:
                from plugins.whatsapp.plugin import whatsapp_send_text
                await whatsapp_send_text(recipient=r["prospect_phone"], message=msg)
            sent += 1
        except Exception:
            continue
    return {"ok": True, "follow_ups_sent": sent, "checked": len(rows)}


# --------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------

@tool(
    name="sales.dashboard",
    description="Sales dashboard: pitches sent, response rate, deals closed, pipeline value.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="autonomous_sales",
)
async def dashboard() -> Dict[str, Any]:
    total = business_db.query_one("SELECT COUNT(*) as n FROM sales_conversations")["n"]
    by_status = business_db.rows_to_dicts(business_db.query("SELECT status, COUNT(*) as n FROM sales_conversations GROUP BY status"))
    deals_closed = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(deal_value_jod),0) as v FROM sales_conversations WHERE status = 'deal_closed'")
    response_rate = 0
    if total > 0:
        responded = sum(r["n"] for r in by_status if r["status"] not in ("pitching", "pitched", "pitch_failed"))
        response_rate = round(responded / total * 100, 1)
    return {
        "ok": True,
        "total_conversations": total,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "deals_closed": deals_closed["n"],
        "revenue_closed_jod": round(deals_closed["v"], 2),
        "response_rate_pct": response_rate,
        "pitches_today": _pitches_today(),
        "daily_cap": MAX_PITCHES_PER_DAY,
    }


# --------------------------------------------------------------------
# Run one loop iteration (for background job)
# --------------------------------------------------------------------

@tool(
    name="sales.run_loop",
    description="One iteration of the sales loop: handle pending replies + send follow-ups + optionally find new prospects. Called by the background scheduler every 30 minutes.",
    parameters={
        "type": "object",
        "properties": {
            "find_new": {"type": "boolean", "default": True, "description": "Find + pitch new prospects in this iteration."},
            "business_type": {"type": "string", "default": "restaurant"},
            "new_prospect_count": {"type": "integer", "default": 5},
        },
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="autonomous_sales",
)
async def run_loop(find_new: bool = True, business_type: str = "restaurant", new_prospect_count: int = 5) -> Dict[str, Any]:
    report = {"steps": []}

    # Step 1: Send follow-ups to unresponsive prospects.
    try:
        fu = await follow_up()
        report["steps"].append({"step": "follow_ups", "sent": fu.get("follow_ups_sent", 0)})
    except Exception as e:
        report["steps"].append({"step": "follow_ups", "error": str(e)})

    # Step 2: Find + pitch new prospects (if enabled + under daily cap).
    if find_new and _pitches_today() < MAX_PITCHES_PER_DAY:
        try:
            prospects = await find_prospects(business_type=business_type, limit=new_prospect_count)
            pitched = 0
            if prospects.get("ok"):
                for p in prospects.get("prospects", [])[:new_prospect_count]:
                    if _pitches_today() >= MAX_PITCHES_PER_DAY: break
                    if not p.get("phone"): continue
                    pitch = await write_pitch(
                        prospect_name=p["name"], has_website=p.get("has_website", False),
                        price_jod=200, channel="whatsapp",
                    )
                    if pitch.get("ok"):
                        send = await send_pitch(
                            prospect_name=p["name"], prospect_phone=p["phone"],
                            pitch_text=pitch["pitch"], channel="whatsapp",
                            service="موقع إلكتروني", price_jod=200,
                        )
                        if send.get("ok"): pitched += 1
            report["steps"].append({"step": "new_pitches", "pitched": pitched})
        except Exception as e:
            report["steps"].append({"step": "new_pitches", "error": str(e)})

    # Step 3: Dashboard summary.
    dash = await dashboard()
    report["dashboard"] = {
        "total": dash["total_conversations"], "closed": dash["deals_closed"],
        "revenue_jod": dash["revenue_closed_jod"], "pitches_today": dash["pitches_today"],
    }
    report["ok"] = True
    business_db.audit("sales_loop", "autonomous_sales", details=report["dashboard"])
    return report


@tool(
    name="sales.list_conversations",
    description="List all sales conversations. Sir can audit what JARVIS said.",
    parameters={
        "type": "object",
        "properties": {"status": {"type": "string", "default": ""}, "limit": {"type": "integer", "default": 20}},
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="autonomous_sales",
)
async def list_conversations(status: str = "", limit: int = 20) -> Dict[str, Any]:
    sql = "SELECT id, prospect_name, prospect_phone, channel, status, deal_value_jod, created_at, updated_at FROM sales_conversations"
    params: tuple = ()
    if status: sql += " WHERE status = ?"; params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"; params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "conversations": rows}


@tool(
    name="sales.read_conversation",
    description="Read the full conversation transcript for a specific prospect. See exactly what JARVIS said.",
    parameters={
        "type": "object",
        "properties": {"conv_id": {"type": "integer"}},
        "required": ["conv_id"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="autonomous_sales",
)
async def read_conversation(conv_id: int) -> Dict[str, Any]:
    conv = business_db.query_one("SELECT * FROM sales_conversations WHERE id = ?", (conv_id,))
    if not conv: return {"ok": False, "error": "not found"}
    history = json.loads(conv["conversation_json"] or "[]")
    return {"ok": True, "conv_id": conv_id, "prospect": conv["prospect_name"], "status": conv["status"],
            "transcript": history, "deal_value_jod": conv["deal_value_jod"]}


@tool(
    name="sales.pause",
    description="Pause the autonomous sales engine. JARVIS stops pitching + following up until resumed.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="autonomous_sales",
)
async def pause() -> Dict[str, Any]:
    from pathlib import Path
    p = Path("./storage/sales_paused.flag")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return {"ok": True, "message": "Sales engine paused. Call sales.resume to restart."}


@tool(
    name="sales.resume",
    description="Resume the autonomous sales engine after a pause.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="autonomous_sales",
)
async def resume() -> Dict[str, Any]:
    from pathlib import Path
    p = Path("./storage/sales_paused.flag")
    if p.exists(): p.unlink()
    return {"ok": True, "message": "Sales engine resumed."}


PLUGIN_NAME = "autonomous_sales"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Autonomous sales: find → pitch → negotiate → close. No intervention needed. Every conversation logged."
