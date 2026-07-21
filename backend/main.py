# ====================================================================
# JARVIS OMEGA — Backend API Entry Point
# ====================================================================
"""
FastAPI application entry point. Handles app initialization, lifespan events,
CORS configuration, WebSocket routing, proactive task reporting, and
frontend UI WebSocket hub.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.event_bus import event_bus
from backend.websocket_manager import ws_manager
from backend.scheduler import scheduler
from backend.device_registry import device_registry
from backend.approval_gateway import approval_gateway
from backend.memory_engine import memory_engine
from backend.task_manager import task_manager
from backend.health_monitor import health_monitor
from backend.memory_indexer import memory_indexer
from backend.project_graph import project_graph
from backend.project_scanner import project_scanner
from backend.services.credentials_vault import credentials_vault
from backend.self_heal import install as install_self_heal
from backend.tools import get_registry
from backend.tools.executor import tool_executor

# Import routers package
from backend.routers import (
    router_chat,
    router_openrouter,
    router_groq,
    router_audio,
    router_vision,
    router_shortcuts,
    router_memory,
    router_agents,
    router_projects,
    router_settings,
)

from shared.logger import setup_logging, get_logger, AuditLogger
from shared.security import init_security, verify_token
from shared.models import (
    DevicePairingRequest,
    DevicePairingResponse,
    ApprovalRequest,
    TaskDefinition,
    TaskResult,
    MemoryQuery,
    MemoryEntry,
    WSMessage,
    SystemVitals,
    ComponentHealth,
    ProjectInfo,
    HealthSnapshot,
)
from shared.constants import WSMessageType, HealthState, RiskLevel, TaskStatus, EventType, AgentType

# Configure structured logging
setup_logging(
    log_dir=settings.logs_dir,
    log_level=settings.log_level,
    log_format=settings.log_format,
)
log = get_logger("main")
audit_log = AuditLogger(log_dir=settings.logs_dir)

# Keep track of heartbeat task
_heartbeat_task: asyncio.Task | None = None

# ====================================================================
# UI WEBSOCKET HUB — Frontend dashboard connections
# ====================================================================
_ui_clients: set[WebSocket] = set()


async def broadcast_to_ui(message: dict) -> None:
    """Push a message to ALL connected frontend dashboard clients."""
    dead = []
    for ws in _ui_clients:
        try:
            await ws.send_json(message)
        except Exception as e:
            log.debug("ui_broadcast_failed_dropping_client", error=str(e))
            dead.append(ws)
    for ws in dead:
        _ui_clients.discard(ws)


async def start_heartbeat_loop() -> None:
    """Periodically sends pings to connected websocket devices."""
    log.info("websocket_heartbeat_loop_started")
    while True:
        try:
            await ws_manager.send_heartbeat_pings()
        except Exception as e:
            log.error("heartbeat_loop_error", error=str(e))
        await asyncio.sleep(settings.ws_heartbeat_interval)

async def dispatch_task_to_device(task_event_payload: Dict[str, Any]) -> bool:
    """Dispatches a newly created task to the connected local workstation client."""
    payload = task_event_payload.get("payload", {})
    task_id = payload.get("task_id")
    if not task_id:
        return False
    
    task = task_manager.get_task(task_id)
    if not task:
        log.warning("dispatch_failed_task_not_found", task_id=task_id)
        return False

    # Find connected devices
    devices = ws_manager.get_connected_devices()
    if not devices:
        log.warning("no_connected_devices_for_task_dispatch", task_id=task_id)
        return False

    # Dispatch to the first connected device
    device_id = devices[0]["device_id"]
    task.device_id = device_id
    task.status = TaskStatus.ASSIGNED
    task.started_at = datetime.utcnow()

    ws_msg = {
        "type": WSMessageType.EXECUTE_TASK.value,
        "payload": task.model_dump(mode="json"),
    }
    
    success = await ws_manager.send_to_device(device_id, ws_msg)
    if success:
        log.info("task_dispatched_via_ws", task_id=task_id, device_id=device_id)
        return True
    else:
        log.error("task_dispatch_failed", task_id=task_id, device_id=device_id)
        return False


async def handle_ws_task_update(event_payload: Dict[str, Any]) -> None:
    """Handles task status updates sent from the client."""
    payload = event_payload.get("payload", {})
    task_id = payload.get("task_id")
    status_str = payload.get("status")
    if not task_id or not status_str:
        return

    task = task_manager.get_task(task_id)
    if not task:
        return

    try:
        task.status = TaskStatus(status_str)
        if task.status == TaskStatus.RUNNING:
            task.started_at = datetime.utcnow()
        log.info("task_status_updated_via_ws", task_id=task_id, status=status_str)
    except Exception as e:
        log.error("failed_to_update_task_status", task_id=task_id, error=str(e))


async def handle_ws_task_result(event_payload: Dict[str, Any]) -> None:
    """Processes task results sent back from the client device and pushes proactive reports."""
    payload = event_payload.get("payload", {})
    task_id = payload.get("task_id")
    if not task_id:
        return

    try:
        task_result = TaskResult(**payload)
        if task_result.status == TaskStatus.FAILED:
            await task_manager.fail_task(
                task_id=task_result.task_id,
                error=task_result.error or "Task execution failed on client",
                agent_id=task_result.agent_id,
            )
        else:
            await task_manager.complete_task(task_result)
        log.info("task_result_processed_via_ws", task_id=task_result.task_id, status=task_result.status.value)

        # ---- PROACTIVE REPORTING ----
        # Push a report to the frontend UI if the task was a background task
        # (i.e., one that wasn't already waited-on by the chat router)
        task_def = task_manager.get_task(task_id)
        if task_def and _ui_clients:
            report = await _generate_task_report(task_def, task_result)
            if report:
                await broadcast_to_ui({
                    "type": "proactive_report",
                    "payload": {
                        "task_id": task_id,
                        "title": task_def.title,
                        "agent_type": task_def.agent_type.value,
                        "status": task_result.status.value,
                        "report": report,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                })
                log.info("proactive_report_sent", task_id=task_id)

    except Exception as e:
        log.error("failed_to_process_task_result", task_id=task_id, error=str(e))


async def handle_approval_event(event_payload: Dict[str, Any]) -> None:
    """
    Bridge approval-gateway events into the UI dashboard.

    The approval gateway already broadcasts to connected *devices* via
    ``ws_manager.broadcast``; this subscription mirrors the same payload to
    ``_ui_clients`` so Sir can see and act on approval requests from the
    command center without a separate channel.
    """
    payload = event_payload.get("payload", {})
    try:
        await broadcast_to_ui({
            "type": "approval_request",
            "payload": payload,
        })
    except Exception as e:
        log.warning("approval_ui_broadcast_failed", error=str(e))


async def _generate_task_report(task: Any, result: TaskResult) -> str:
    """Generate a conversational, natural JARVIS response for a completed task."""
    from backend.services.llm_service import llm_service
    
    status_text = "completed successfully" if result.status == TaskStatus.COMPLETED else f"failed with error: {result.error}"
    title = task.title or "System Task"
    
    stdout = ""
    if result.result:
        stdout = result.result.get("stdout", "").strip()
        if stdout:
            stdout = stdout[:500] + ("..." if len(stdout) > 500 else "")

    system_prompt = (
        "You are JARVIS. A background task you were managing has just finished. "
        "Formulate a brief, highly professional, and conversational notification to Sir. "
        "Do NOT use markdown tables or dry 'Task Report' headers. Speak directly to him. "
        "For example: 'Sir, the brute force attack has concluded. We successfully gained access.' "
        "Or 'Sir, I have finished searching for the news you requested. Here is what I found...' "
        "Do not over-explain, just give the outcome naturally."
    )
    
    user_prompt = f"Task: {title}\nStatus: {status_text}\nOutput context: {stdout}"

    try:
        report = await llm_service.get_response(
            user_message=user_prompt,
            system_instructions=system_prompt,
            inject_memory=False
        )
        return report
    except Exception as e:
        log.error("failed_to_generate_llm_report", error=str(e))
        # Fallback
        return f"Sir, the task '{title}' has {status_text}."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles backend startup and shutdown lifecycle events."""
    global _heartbeat_task
    log.info("jarvis_omega_backend_starting")

    # 1. Ensure storage directories exist
    settings.ensure_directories()

    # 1b. Fail fast on missing/placeholder bootstrap secrets — prevents the
    # WebSocket 403 storm caused by JWT keys silently rotating between runs.
    settings.validate_security_settings()

    # 2. Initialize security module
    init_security(
        secret_key=settings.backend_secret_key,
        encryption_key=settings.encryption_key,
        algorithm=settings.jwt_algorithm,
        access_expire_minutes=settings.access_token_expire_minutes,
        refresh_expire_days=settings.refresh_token_expire_days,
        device_expire_days=settings.device_token_expire_days,
    )

    # 3. Interconnect dependencies
    ws_manager.set_event_bus(event_bus)
    device_registry.set_event_bus(event_bus)
    approval_gateway.set_event_bus(event_bus)
    approval_gateway.set_ws_manager(ws_manager)
    task_manager.set_event_bus(event_bus)
    health_monitor.set_event_bus(event_bus)

    # Register task and WS message subscribers
    event_bus.subscribe(EventType.TASK_CREATED, dispatch_task_to_device)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_UPDATE.value}", handle_ws_task_update)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_RESULT.value}", handle_ws_task_result)

    # Mirror approval-gateway events to the UI dashboard so Sir can act on
    # pending approvals from the command center.
    event_bus.subscribe(EventType.APPROVAL_REQUESTED, handle_approval_event)
    event_bus.subscribe(EventType.APPROVAL_GRANTED, handle_approval_event)
    event_bus.subscribe(EventType.APPROVAL_DENIED, handle_approval_event)

    # 4. Initialize registries, graphs and engines
    await device_registry.initialize()
    await memory_engine.initialize()
    await project_graph.initialize()

    # 4a. Phase 8 — initialize credentials vault + tool registry + executor
    try:
        credentials_vault.initialize()
        log.info("credentials_vault_initialized", entries=len(credentials_vault.list_keys()))
    except Exception as cv_err:
        log.warning("credentials_vault_init_failed", error=str(cv_err))

    try:
        tool_executor.set_approval_gateway(approval_gateway)
        # Load every seed plugin. Each plugin's @tool decorators register
        # on import with the default ToolRegistry singleton.
        loaded = get_registry().load_plugins([
            "plugins.core_dev.plugin",
            "plugins.code_sandbox.plugin",
            "plugins.documents.plugin",
            "plugins.communication.plugin",
            "plugins.media_gen.plugin",
            "plugins.mobile.plugin",
            "plugins.smart_home.plugin",
            "plugins.cloud.plugin",
            "plugins.atxp.plugin",
            # Phase 10 — free-tier plugins
            "plugins.browser.plugin",
            "plugins.media_free.plugin",
            "plugins.voice_local.plugin",
            "plugins.web.plugin",
            "plugins.email_imap.plugin",
            "plugins.calendar_local.plugin",
            "plugins.weather.plugin",
            "plugins.stock_crypto.plugin",
            "plugins.maps.plugin",
            "plugins.translate.plugin",
            "plugins.podcast.plugin",
            "plugins.notes_todo.plugin",
            "plugins.github_free.plugin",
            "plugins.media_local.plugin",
            "plugins.backup_local.plugin",
            # Phase 11 — autonomous marketing agency
            "plugins.marketing.plugin",
            "plugins.sales.plugin",
            "plugins.support.plugin",
            "plugins.ecommerce.plugin",
            "plugins.website.plugin",
            "plugins.business_intel.plugin",
            "plugins.payments.plugin",
            "plugins.agency_orchestrator.plugin",
            # Phase 12 — localization + portfolio (Arabic-first, 50 businesses)
            "plugins.l10n.plugin",
            "plugins.portfolio.plugin",
            # Phase 13 — agency scale + Arabic + trading + YouTube + WhatsApp
            "plugins.islamic.plugin",
            "plugins.legal_jo.plugin",
            "plugins.affiliate.plugin",
            "plugins.seo.plugin",
            "plugins.realestate_jo.plugin",
            "plugins.trading.plugin",
            "plugins.youtube.plugin",
            "plugins.whatsapp.plugin",
            # Phase 14 — Sir Empire (codex + council + media empire + engineering + money + infra)
            "plugins.codex.plugin",
            "plugins.council.plugin",
            "plugins.twin.plugin",
            "plugins.shorts.plugin",
            "plugins.newsletter.plugin",
            "plugins.music.plugin",
            "plugins.media_empire.plugin",
            "plugins.app_factory.plugin",
            "plugins.saas_factory.plugin",
            "plugins.github_empire.plugin",
            "plugins.freelancer.plugin",
            "plugins.dropship.plugin",
            "plugins.course.plugin",
            "plugins.web3.plugin",
            "plugins.defi.plugin",
            "plugins.family_office.plugin",
            # Phase 15 — reality check: diagnostics + niche validation + compliance
            "plugins.diagnostics.plugin",
            "plugins.niche_validator.plugin",
            "plugins.compliance.plugin",
            "plugins.payouts.plugin",
            "plugins.lemonsqueezy.plugin",
            "plugins.budget.plugin",
            # Phase 16+17 — Jordan commerce loop + revenue multipliers + autonomous sales
            "plugins.local_payment_jo.plugin",
            "plugins.whatsapp_commerce.plugin",
            "plugins.social_dms.plugin",
            "plugins.phone_agent.plugin",
            "plugins.brand_kit.plugin",
            "plugins.email_marketing.plugin",
            "plugins.unified_crm.plugin",
            "plugins.price_monitor.plugin",
            "plugins.content_repurposing.plugin",
            "plugins.subscription_box.plugin",
            "plugins.linkedin_factory.plugin",
            "plugins.delivery_jo.plugin",
            "plugins.grant_finder.plugin",
            "plugins.qr_menu.plugin",
            "plugins.legal_review.plugin",
            "plugins.influencer_outreach.plugin",
            "plugins.autonomous_sales.plugin",
        ])
        log.info("tool_registry_loaded", total_tools=len(get_registry().all_tools()), new_from_plugins=loaded)
    except Exception as tr_err:
        log.warning("tool_registry_load_failed", error=str(tr_err))

    # 4b. Phase 9 — install the self-healing supervisor (excepthook + asyncio).
    try:
        install_self_heal()
    except Exception as sh_err:
        log.warning("self_heal_install_failed", error=str(sh_err))

    # 4b. Diagnostic: log trust state of every loaded device so the
    # WebSocket 403 case is observable at startup.
    try:
        all_devices = device_registry.get_all_devices()
        if all_devices:
            log.info(
                "device_registry_trust_snapshot",
                count=len(all_devices),
                trusted=sum(1 for d in all_devices if d.trusted),
                untrusted=sum(1 for d in all_devices if not d.trusted),
                device_ids=[
                    {"device_id": d.device_id, "name": d.device_name, "trusted": d.trusted}
                    for d in all_devices
                ],
            )
        else:
            log.info("device_registry_empty_no_devices_loaded")
    except Exception as diag_err:
        log.warning("device_registry_trust_snapshot_failed", error=str(diag_err))

    # Register components in health monitor
    health_monitor.register_component("WebSocketManager")
    health_monitor.register_component("Scheduler")
    health_monitor.register_component("MemoryEngine")
    health_monitor.register_component("TaskManager")

    # 5. Start Background Services
    await scheduler.start()
    await health_monitor.start()
    await memory_indexer.start()
    _heartbeat_task = asyncio.create_task(start_heartbeat_loop())

    # 5b. Phase 11 — register the autonomous-agency background jobs.
    try:
        from plugins.business_intel.plugin import biz_scan_opportunities
        from plugins.marketing.plugin import marketing_post
        from plugins.agency_orchestrator.plugin import agency_weekly_report

        async def _opportunity_scan_job():
            try:
                await biz_scan_opportunities(
                    niche_keywords=settings.default_niche.split(",") if settings.default_niche else [],
                )
            except Exception as e:
                log.warning("opportunity_scan_job_failed", error=str(e))

        async def _publish_scheduled_posts_job():
            """Publish every post whose scheduled_at has arrived and is still 'scheduled'."""
            try:
                from backend import business_db
                from datetime import datetime as _dt
                now_iso = _dt.utcnow().isoformat()
                rows = business_db.query(
                    "SELECT id, platform, content, title, subreddit FROM posts "
                    "WHERE status = 'scheduled' AND scheduled_at <= ? LIMIT 50",
                    (now_iso,),
                )
                for r in rows:
                    try:
                        result = await marketing_post(
                            platform=r["platform"], content=r["content"],
                            title=r["title"] or "", subreddit=r["subreddit"] or "",
                        )
                        # marketing_post already updates status to posted/failed
                    except Exception as post_err:
                        log.warning("scheduled_post_publish_failed",
                                    post_id=r["id"], error=str(post_err))
            except Exception as e:
                log.warning("publish_scheduled_posts_job_failed", error=str(e))

        async def _weekly_report_job():
            try:
                await agency_weekly_report()
            except Exception as e:
                log.warning("weekly_report_job_failed", error=str(e))

        # Schedule the recurring jobs.
        if settings.auto_self_heal and settings.opportunity_scan_interval_hours > 0:
            scheduler.schedule_interval(
                job_id="opportunity_scan",
                func=_opportunity_scan_job,
                hours=settings.opportunity_scan_interval_hours,
                description=f"Background opportunity scan every {settings.opportunity_scan_interval_hours}h",
            )
        scheduler.schedule_interval(
            job_id="publish_scheduled_posts",
            func=_publish_scheduled_posts_job,
            minutes=15,
            description="Publish scheduled social posts every 15 minutes",
        )
        # Weekly report every Monday 09:00 UTC.
        scheduler.schedule_cron(
            job_id="weekly_report",
            func=_weekly_report_job,
            cron_expression="0 9 * * 1",
            description="Weekly agency report every Monday 09:00 UTC",
        )

        # Phase 13 — trading signals scan (every 1h).
        async def _trading_signals_job():
            try:
                from plugins.trading.plugin import trading_signals_scan, trading_run_alerts
                await trading_signals_scan(limit=10)
                await trading_run_alerts()
            except Exception as e:
                log.warning("trading_signals_job_failed", error=str(e))

        scheduler.schedule_interval(
            job_id="trading_signals_scan",
            func=_trading_signals_job,
            hours=1,
            description="Scan crypto markets for RSI signals + fire price alerts every 1h",
        )

        # Phase 13 — Jordan real-estate alert scan (every 6h).
        async def _real_estate_job():
            try:
                from plugins.realestate_jo.plugin import realestate_alert_new
                await realestate_alert_new(city="Amman", min_score=70, alert_channel="")
            except Exception as e:
                log.warning("real_estate_job_failed", error=str(e))

        scheduler.schedule_interval(
            job_id="realestate_scan",
            func=_real_estate_job,
            hours=6,
            description="Scan Amman property listings every 6h, persist + score",
        )

        # Phase 13 — Islamic prayer reminder (3x daily: Fajr, Dhuhr, Maghrib)
        # We just check on each interval and push if prayer time is close.
        async def _prayer_reminder_job():
            try:
                from plugins.islamic.plugin import islamic_prayer_times
                from datetime import datetime as _dt
                pt = await islamic_prayer_times(city=settings.default_city,
                                                country=settings.default_country_name)
                if not pt.get("ok"):
                    return
                now_hhmm = _dt.utcnow().strftime("%H:%M")
                for name in ("Fajr", "Dhuhr", "Maghrib"):
                    t = pt["timings"].get(name, "")
                    if t and t[:5] == now_hhmm:
                        from plugins.marketing.plugin import marketing_post
                        await marketing_post(
                            platform="telegram",
                            content=f"🕌 {name} now ({t} UTC) —timezone adjust as needed, Sir.",
                            chat_id="me",
                        )
            except Exception as e:
                log.warning("prayer_reminder_failed", error=str(e))

        scheduler.schedule_interval(
            job_id="prayer_reminder",
            func=_prayer_reminder_job,
            minutes=1,
            description="Check prayer times every minute; fire Telegram reminder at Fajr/Dhuhr/Maghrib",
        )

        log.info("phase13_background_jobs_registered")

        # Phase 16+17 — autonomous sales loop (every 30 min) + email sequence processor (every 15 min).
        async def _sales_loop_job():
            try:
                from pathlib import Path as _P
                if _P("./storage/sales_paused.flag").exists():
                    return
                from plugins.autonomous_sales.plugin import run_loop
                await run_loop(find_new=True, new_prospect_count=3)
            except Exception as e:
                log.warning("sales_loop_job_failed", error=str(e))

        async def _email_sequence_job():
            try:
                from plugins.email_marketing.plugin import sequence_process
                await sequence_process()
            except Exception as e:
                log.warning("email_sequence_job_failed", error=str(e))

        scheduler.schedule_interval(
            job_id="autonomous_sales_loop",
            func=_sales_loop_job,
            minutes=30,
            description="Autonomous sales: follow up + find new prospects every 30 min",
        )
        scheduler.schedule_interval(
            job_id="email_sequence_processor",
            func=_email_sequence_job,
            minutes=15,
            description="Send pending email sequence steps every 15 min",
        )
        log.info("phase16_17_jobs_registered")
        log.info("phase11_agency_jobs_registered")
    except Exception as sched_err:
        log.warning("phase11_job_registration_failed", error=str(sched_err))

    log.info("jarvis_omega_backend_ready")
    audit_log.log(
        category="system",
        action="startup",
        status="success",
        details={"message": "JARVIS OMEGA Backend started successfully"},
    )

    yield

    # ---- Shutdown Lifecycle ----
    log.info("jarvis_omega_backend_shutting_down")

    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass

    await memory_indexer.stop()
    await health_monitor.stop()
    await scheduler.stop()

    audit_log.log(
        category="system",
        action="shutdown",
        status="success",
        details={"message": "JARVIS OMEGA Backend shut down gracefully"},
    )
    log.info("jarvis_omega_backend_shutdown_complete")


# Create FastAPI App
app = FastAPI(
    title="JARVIS OMEGA Backend",
    description="Central Command & Control Relay Station for Sir's Autonomous Ecosystem",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include modular API routers
app.include_router(router_chat)
app.include_router(router_openrouter)
app.include_router(router_groq)
app.include_router(router_audio)
app.include_router(router_vision)
app.include_router(router_shortcuts)
app.include_router(router_memory)
app.include_router(router_agents)
app.include_router(router_projects)
app.include_router(router_settings)


# ====================================================================
# REST API ENDPOINTS
# ====================================================================

@app.get("/health", response_model=HealthSnapshot, tags=["System"])
async def get_health() -> HealthSnapshot:
    """Returns the unified health status of the API and its subsystems."""
    # Basic check for memory engine collections
    try:
        stats = await memory_engine.get_stats()
        memory_ok = len(stats) > 0
    except Exception as mem_err:
        log.warning("health_memory_probe_failed", error=str(mem_err))
        memory_ok = False

    return HealthSnapshot(
        status="online",
        health=HealthState.HEALTHY if memory_ok else HealthState.DEGRADED,
        scheduler_active=scheduler.job_count > 0 or scheduler._scheduler.running,
        active_connections=ws_manager.connection_count,
        tasks_in_queue=task_manager.queue_size,
    )


# ---- System & Health Monitor ----

@app.get("/api/system/vitals", response_model=SystemVitals, tags=["System"])
async def get_system_vitals():
    """Retrieve detailed host resource performance metrics."""
    return await health_monitor.get_system_vitals()


@app.get("/api/system/components", response_model=List[ComponentHealth], tags=["System"])
async def get_components_health():
    """Retrieve health statistics for all internal modules."""
    return health_monitor.get_component_health()


# ---- Device Pairing ----

@app.post("/api/devices/pair/initiate", response_model=DevicePairingResponse, tags=["Devices"])
async def initiate_device_pairing(request: DevicePairingRequest):
    """Initiates the pairing protocol for a new device."""
    try:
        response = await device_registry.initiate_pairing(request)
        return response
    except Exception as e:
        log.error("pairing_initiate_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate device pairing.",
        )


@app.post("/api/devices/pair/approve", response_model=DevicePairingResponse, tags=["Devices"])
async def approve_device_pairing(pairing_code: str = Query(..., description="The numeric code generated by the device")):
    """Allows Sir to approve a pending device pairing request."""
    response = await device_registry.approve_pairing(pairing_code)
    if not response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired pairing code.",
        )
    return response


# ---- Approvals ----

@app.get("/api/approvals/pending", tags=["Approvals"])
async def get_pending_approvals():
    """Retrieve all pending human approval requests."""
    return [req.model_dump() for req in approval_gateway.get_pending()]


@app.post("/api/approvals/{approval_id}/approve", tags=["Approvals"])
async def approve_action(approval_id: str):
    """Grant approval for a dangerous operation."""
    success = await approval_gateway.approve(approval_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )
    return {"status": "approved"}


@app.post("/api/approvals/{approval_id}/reject", tags=["Approvals"])
async def reject_action(approval_id: str, reason: str = Query("", description="Reason for rejection")):
    """Deny approval for a dangerous operation."""
    success = await approval_gateway.reject(approval_id, reason=reason)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found.",
        )
    return {"status": "rejected"}


# ---- Tasks ----

@app.post("/api/tasks", tags=["Tasks"])
async def create_task(task: TaskDefinition):
    """Submit a new task to the queue."""
    task_id = await task_manager.create_task(task)
    return {"task_id": task_id, "status": "queued"}


@app.get("/api/tasks", tags=["Tasks"])
async def list_tasks(limit: int = 50):
    """Retrieve the recent task list."""
    return [t.model_dump() for t in task_manager.get_all_tasks(limit=limit)]


@app.get("/api/tasks/{task_id}", tags=["Tasks"])
async def get_task(task_id: str):
    """Get details of a specific task."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = task_manager.get_result(task_id)
    return {
        "task": task.model_dump(),
        "result": result.model_dump() if result else None,
    }


# ====================================================================
# UI WEBSOCKET ENDPOINT — Frontend Dashboard Connection (must be before /ws/{device_id})
# ====================================================================

@app.websocket("/ws/ui")
async def ui_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for the frontend dashboard.
    Receives proactive reports, task updates, and system notifications.
    No authentication required for local development.
    """
    await websocket.accept()
    _ui_clients.add(websocket)
    log.info("ui_client_connected", total_ui_clients=len(_ui_clients))

    try:
        # Send a welcome message
        await websocket.send_json({
            "type": "system_status",
            "payload": {
                "status": "connected",
                "message": "J.A.R.V.I.S. systems online. All subsystems nominal, Sir.",
                "connected_devices": len(ws_manager.get_connected_devices()),
                "timestamp": datetime.utcnow().isoformat(),
            },
        })

        # Keep connection alive, listen for any UI-side messages
        while True:
            data = await websocket.receive_text()
            try:
                msg = orjson_parse(data)
                msg_type = msg.get("type", "")

                # Handle ping from frontend
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

                # Handle direct command dispatch from UI
                elif msg_type == "dispatch_command":
                    cmd = msg.get("payload", {}).get("command", "")
                    if cmd:
                        task = TaskDefinition(
                            title="UI Direct Command",
                            description=f"Command from dashboard: {cmd}",
                            agent_type=AgentType.OS,
                            payload={"command": cmd, "action": "command"},
                        )
                        task_id = await task_manager.create_task(task)
                        await websocket.send_json({
                            "type": "command_accepted",
                            "payload": {"task_id": task_id, "command": cmd},
                        })

            except Exception as parse_err:
                log.error("ui_ws_parse_error", error=str(parse_err))

    except WebSocketDisconnect:
        _ui_clients.discard(websocket)
        log.info("ui_client_disconnected", total_ui_clients=len(_ui_clients))
    except Exception as e:
        _ui_clients.discard(websocket)
        log.error("ui_ws_error", error=str(e))


# ====================================================================
# DEVICE WEBSOCKET COMMAND & CONTROL TERMINAL
# ====================================================================

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    device_id: str,
    token: str = Query(None),
):
    """
    Main WebSocket bridge endpoint. Validates device access tokens,
    tracks health latency, and processes incoming messages.
    """
    # 1. Access Token Verification
    if not token:
        log.warning("ws_rejected_no_token", device_id=device_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token required")
        return

    claims = verify_token(token)
    if not claims or claims.get("device_id") != device_id:
        log.warning("ws_rejected_invalid_token", device_id=device_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    # Check device registry pairing trust status
    if not device_registry.is_trusted(device_id):
        log.warning("ws_rejected_untrusted_device", device_id=device_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Device untrusted")
        return

    # Get device info
    dev_info = device_registry.get_device(device_id)
    device_name = dev_info.device_name if dev_info else "Unknown Device"
    device_type = dev_info.device_type.value if dev_info else "unknown"

    # Register connection in WebSocket manager
    device = await ws_manager.connect(
        websocket=websocket,
        device_id=device_id,
        device_name=device_name,
        device_type=device_type,
        session_token=token,
    )

    # Update online status
    await device_registry.update_status(device_id, online=True)

    try:
        # Loop to process client messages
        while True:
            data = await websocket.receive_text()
            try:
                message_json = orjson_parse(data)
                # Parse to WSMessage model for routing validation
                msg = WSMessage(**message_json)
                msg.device_id = device_id
                
                # Handle Heartbeat response from client
                if msg.type == WSMessageType.HEARTBEAT:
                    await ws_manager.handle_heartbeat(device_id)
                    await device_registry.update_status(
                        device_id,
                        online=True,
                        latency_ms=device.latency_ms,
                    )
                else:
                    # Publish event to event bus for decoupled handling
                    await event_bus.publish(
                        f"ws_msg_{msg.type.value}",
                        msg.model_dump(mode="json"),
                        source=device_id,
                    )
            except Exception as parse_error:
                log.error("ws_msg_parse_error", device_id=device_id, error=str(parse_error))
                await websocket.send_json({
                    "type": WSMessageType.ERROR.value,
                    "payload": {"error": "Invalid message envelope format"},
                })
    except WebSocketDisconnect:
        await ws_manager.disconnect(device_id)
        await device_registry.update_status(device_id, online=False)
    except Exception as e:
        log.error("ws_endpoint_error", device_id=device_id, error=str(e))
        await ws_manager.disconnect(device_id)
        await device_registry.update_status(device_id, online=False)




def orjson_parse(data: str) -> Any:
    """Helper to parse JSON string using orjson."""
    import orjson
    return orjson.loads(data)
