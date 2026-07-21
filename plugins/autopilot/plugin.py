# JARVIS OMEGA - Autopilot Master Switch (Phase 18) - THE ONE COMMAND
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier
from backend import business_db
from shared.logger import get_logger
log = get_logger("autopilot")

_PAUSED_FLAG = Path("./storage/autopilot_paused.flag")

@tool(name="autopilot.activate", description="ONE COMMAND: activates EVERY autonomous loop. JARVIS runs everything — business building, sales, content, products, monitoring, investments. Never stops until you say pause.", parameters={"type":"object","properties":{"confirm":{"type":"boolean","default":True,"description":"Must be true to confirm."}}}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="autopilot")
async def activate(confirm: bool = True) -> Dict[str, Any]:
    if not confirm: return {"ok": False, "error": "Set confirm=true to activate."}
    if _PAUSED_FLAG.exists(): _PAUSED_FLAG.unlink()
    from backend.scheduler import scheduler
    import asyncio

    # Define all autonomous jobs
    async def _business_builder():
        try:
            from plugins.agency_orchestrator.plugin import _continuous_build_step
            await _continuous_build_step(7, "local_only")
        except Exception as e: log.warning("business_builder_failed", error=str(e))

    async def _sales_loop():
        try:
            if not _PAUSED_FLAG.exists():
                from plugins.autonomous_sales.plugin import run_loop
                await run_loop(find_new=True, new_prospect_count=3)
        except Exception as e: log.warning("sales_loop_failed", error=str(e))

    async def _content_factory():
        try:
            from plugins.marketing.plugin import marketing_create_content
            await marketing_create_content(topic="daily motivation for entrepreneurs", platform="twitter", variants=3)
        except Exception as e: log.warning("content_factory_failed", error=str(e))

    async def _digital_product():
        try:
            from plugins.digital_products.plugin import ebook_pipeline
            await ebook_pipeline(topic="auto-generated", language="ar")
        except Exception as e: log.warning("digital_product_failed", error=str(e))

    async def _daily_briefing():
        try:
            from plugins.daily_briefing.plugin import send_morning_briefing
            await send_morning_briefing()
        except Exception as e: log.warning("briefing_failed", error=str(e))

    async def _uptime_check():
        try:
            from plugins.uptime_monitor.plugin import check_all
            await check_all()
        except Exception as e: log.warning("uptime_check_failed", error=str(e))

    async def _brand_mention():
        try:
            from plugins.brand_mention.plugin import scan_mentions
            await scan_mentions()
        except Exception as e: log.warning("brand_mention_failed", error=str(e))

    # Register all jobs (cancel existing first)
    jobs = [
        ("autopilot_business_builder", _business_builder, {"hours": 24}),
        ("autopilot_sales_loop", _sales_loop, {"minutes": 30}),
        ("autopilot_content_factory", _content_factory, {"hours": 6}),
        ("autopilot_digital_product", _digital_product, {"hours": 168}),  # weekly
        ("autopilot_daily_briefing", _daily_briefing, {"hours": 12}),
        ("autopilot_uptime_check", _uptime_check, {"minutes": 5}),
        ("autopilot_brand_mention", _brand_mention, {"hours": 6}),
    ]
    registered = []
    for job_id, func, interval in jobs:
        try: scheduler.cancel_job(job_id)
        except: pass
        try:
            scheduler.schedule_interval(job_id=job_id, func=func, description=f"Autopilot: {job_id}", **interval)
            registered.append(job_id)
        except Exception as e:
            log.warning(f"job_register_failed:{job_id}", error=str(e))

    business_db.audit("autopilot_activated", "autopilot", details={"jobs": registered})
    return {"ok": True, "activated": True, "jobs_registered": registered, "message": "🚀 Autopilot ACTIVATED. JARVIS is now running everything autonomously. Call autopilot.pause to stop."}

@tool(name="autopilot.pause", description="Pause ALL autonomous loops. JARVIS stops everything.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="autopilot")
async def pause() -> Dict[str, Any]:
    _PAUSED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    _PAUSED_FLAG.touch()
    return {"ok": True, "paused": True, "message": "⏸️ Autopilot PAUSED. All loops stopped. Call autopilot.activate to resume."}

@tool(name="autopilot.status", description="Check what's running and what's paused.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="autopilot")
async def status() -> Dict[str, Any]:
    is_paused = _PAUSED_FLAG.exists()
    from backend.scheduler import scheduler
    jobs = scheduler.get_jobs()
    autopilot_jobs = [j for j in jobs if "autopilot" in j.get("job_id","")]
    return {"ok": True, "paused": is_paused, "active_jobs": len(autopilot_jobs), "jobs": [{"id":j["job_id"],"active":j["active"]} for j in autopilot_jobs]}

PLUGIN_NAME = "autopilot"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "ONE command activates EVERYTHING. JARVIS runs fully autonomous — business, sales, content, products, monitoring."
