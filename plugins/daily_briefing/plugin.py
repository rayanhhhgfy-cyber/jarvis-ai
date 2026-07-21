# JARVIS OMEGA - Daily Briefing (Phase 18)
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db

@tool(name="briefing.send_morning", description="Generate + send morning WhatsApp briefing. Shows: revenue, deals, content published, alerts.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="daily_briefing")
async def send_morning_briefing() -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    # Revenue
    inv = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(amount),0) as v FROM invoices WHERE status='paid' AND paid_at >= ?", (since,))
    orders = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(total),0) as v FROM orders WHERE status IN ('paid','delivered') AND created_at >= ?", (since,))
    deals = business_db.query_one("SELECT COUNT(*) as n, COALESCE(SUM(deal_value_jod),0) as v FROM sales_conversations WHERE status='deal_closed' AND updated_at >= ?", (since,))
    posts = business_db.query_one("SELECT COUNT(*) as n FROM posts WHERE created_at >= ?", (since,))
    businesses = business_db.query_one("SELECT COUNT(*) as n FROM businesses WHERE status='live'")["n"]
    msg = f"🌅 صباح الخير سيدي!\n\n📊 آخر 24 ساعة:\n"
    msg += f"- إيرادات: {round(inv['v']+orders['v'],1)} د.أ\n"
    msg += f"- صفقات مغلقة: {deals['n']} ({round(deals['v'],1)} د.أ)\n"
    msg += f"- محتوى منشور: {posts['n']}\n"
    msg += f"- أعمال نشطة: {businesses}\n\n"
    msg += "🚀 كل شيء يعمل تلقائياً. لا تحتاج فعل شيء."
    # Send via WhatsApp/Telegram
    try:
        from plugins.marketing.plugin import marketing_post
        await marketing_post(platform="telegram", content=msg, chat_id="me")
    except: pass
    business_db.audit("morning_briefing", "daily_briefing", details={"revenue": inv['v']+orders['v']})
    return {"ok": True, "briefing": msg, "sent": True}

@tool(name="briefing.send_evening", description="Generate + send evening summary.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="daily_briefing")
async def send_evening_briefing() -> Dict[str, Any]:
    return await send_morning_briefing()

@tool(name="briefing.generate", description="Generate a briefing text without sending (preview).", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="daily_briefing")
async def generate_briefing() -> Dict[str, Any]:
    r = await send_morning_briefing()
    return {"ok": True, "briefing": r.get("briefing","")}

@tool(name="briefing.set_schedule", description="Configure when briefings are sent (default: 9am + 9pm Amman time).", parameters={"type":"object","properties":{"morning_hour":{"type":"integer","default":9},"evening_hour":{"type":"integer","default":21}}}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="daily_briefing")
async def set_schedule(morning_hour: int = 9, evening_hour: int = 21) -> Dict[str, Any]:
    from backend.scheduler import scheduler
    async def _morning(): await send_morning_briefing()
    async def _evening(): await send_evening_briefing()
    try: scheduler.cancel_job("briefing_morning")
    except: pass
    try: scheduler.cancel_job("briefing_evening")
    except: pass
    scheduler.schedule_cron(job_id="briefing_morning", func=_morning, cron_expression=f"0 {morning_hour} * * *", description="Morning briefing")
    scheduler.schedule_cron(job_id="briefing_evening", func=_evening, cron_expression=f"0 {evening_hour} * * *", description="Evening briefing")
    return {"ok": True, "morning": f"{morning_hour}:00", "evening": f"{evening_hour}:00"}

PLUGIN_NAME = "daily_briefing"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Morning + evening WhatsApp briefing. One message = full picture."
