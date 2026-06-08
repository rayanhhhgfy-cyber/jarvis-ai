# ====================================================================
# JARVIS OMEGA — Backend API Entry Point
# ====================================================================
"""
FastAPI application entry point. Handles app initialization, lifespan events,
CORS configuration, WebSocket routing, proactive task reporting, and
frontend UI WebSocket hub.
"""

from __future__ import annotations

# Disable ChromaDB telemetry BEFORE any imports
import os
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['CHROMA_TELEMETRY'] = 'False'
os.environ['CHROMA_SKIP_TELEMETRY'] = 'True'
os.environ['CHROMADB_SKIP_TELEMETRY'] = 'True'

# Pre-populate sys.modules with fake chromadb to prevent real chromadb import entirely.
# The real chromadb package fires telemetry events DURING import (via posthog), which
# crashes on Python 3.13+ due to `capture()` signature mismatch.  We short-circuit
# before Python ever touches the real package on disk.
import sys
import types

_fake_chromadb = types.ModuleType('chromadb')
_fake_chromadb.__path__ = []
_fake_chromadb.__file__ = '<disabled>'


def _noop(*args, **kwargs):
    pass


class _FakeClientAPI:
    """Stand-in for chromadb.ClientAPI — every method is a no-op."""
    def __call__(self, *args, **kwargs):
        return None

    def get_or_create_collection(self, *args, **kwargs):
        return _FakeCollection()

    def get_collection(self, *args, **kwargs):
        return _FakeCollection()

    def delete_collection(self, *args, **kwargs):
        pass

    def heartbeat(self, *args, **kwargs):
        return 0

    def list_collections(self, *args, **kwargs):
        return []

    def reset(self, *args, **kwargs):
        pass


class _FakeCollection:
    """Stand-in for a ChromaDB collection object."""
    def count(self, *args, **kwargs):
        return 0

    def add(self, *args, **kwargs):
        pass

    def upsert(self, *args, **kwargs):
        pass

    def update(self, *args, **kwargs):
        pass

    def delete(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return {'ids': [], 'documents': [], 'metadatas': [], 'distances': []}

    def query(self, *args, **kwargs):
        return {'ids': [[]], 'documents': [[]], 'metadatas': [[]], 'distances': [[]]}


_fake_chromadb.telemetry = types.ModuleType('telemetry')
_fake_chromadb.telemetry.capture = _noop
_fake_chromadb.telemetry.product = types.ModuleType('product')
_fake_chromadb.telemetry.product.capture = _noop
_fake_chromadb.PersistentClient = lambda path=None, settings=None: _FakeClientAPI()
_fake_chromadb.ClientAPI = _FakeClientAPI
_fake_chromadb.Settings = lambda **kw: types.SimpleNamespace(**kw)
_fake_chromadb.Collection = _FakeCollection
_fake_chromadb.__version__ = '0.0.0-disabled'

# Lock the fake module into sys.modules so any importlib import of chromadb
# returns our fake instead of hitting the real (telemetry-emitting) package.
sys.modules['chromadb'] = _fake_chromadb
sys.modules['chromadb.telemetry'] = _fake_chromadb.telemetry
sys.modules['chromadb.telemetry.product'] = _fake_chromadb.telemetry.product

import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
from backend.services.agent_tracker import agent_tracker
from backend.services.task_worker import task_worker
from backend.memory.sqlite_memory import sqlite_memory
from backend.project_graph import project_graph
from local_client.agents import orchestrator as agent_orchestrator
from backend.project_scanner import project_scanner
from backend.droid.ws_server import handle_droid_envelope

# New Pillar Services
from backend.vault.secure_vault import secure_vault
from backend.sentinel.sentinel_service import sentinel_service
from backend.vision.dynamic_sampler import dynamic_sampler
from backend.voice.voice_orchestrator import voice_orchestrator
from backend.telegram_app.telegram_bridge import telegram_bridge
from backend.discord.discord_bridge import discord_bridge
from backend.services.autonomous_scraper import autonomous_scraper
# from backend.memory.workspace_watcher import workspace_watcher  # Disabled to prevent ChromaDB telemetry crashes
from backend.research.night_shift import night_shift
from backend.social.social_sentinel import social_sentinel
from backend.improvement.self_improvement import self_improvement
from backend.services.browser_service import browser_service
from backend.services.cron_failover import cron_failover

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
    router_browser,
    router_settings,
)
from backend.routers.router_downloads import router as router_downloads
from backend.routers.router_media_generation import router as router_media_generation
from backend.routers.router_agent_exec import router as router_agent_exec
from backend.routers.router_scheduler import router as router_scheduler
from backend.routers.router_patterns import router as router_patterns
from backend.routers.router_mcp import router as router_mcp
from backend.routers.router_skills import router as router_skills
from backend.routers.router_hardware import router as router_hardware
from backend.routers.tasks_router import router as router_tasks
from backend.routers.router_listening import router as router_listening
from backend.routers.router_build import router as router_build
from backend.routers.router_clips import router as router_clips
from backend.routers.router_mods import router as router_mods
from backend.routers.router_connections import router as router_connections
from backend.routers.router_focus import router as router_focus
from backend.routers.router_social import router as router_social

# New pillar routers
from backend.vault.vault_router import router as router_vault

from shared.logger import setup_logging, get_logger, AuditLogger
from shared.security import init_security, verify_token
from shared.clerk_security import ClerkJWTVerifier, ClerkVerificationConfig
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from jose import JWTError
from shared.models import (
    DevicePairingRequest,
    DevicePairingResponse,
    DesktopRegisterRequest,
    QrPairConsumeRequest,
    ApprovalRequest,
    TaskDefinition,
    TaskResult,
    MemoryQuery,
    MemoryEntry,
    WSMessage,
    SystemVitals,
    ComponentHealth,
    ProjectInfo,
)
from shared.constants import WSMessageType, HealthState, RiskLevel, TaskStatus, EventType

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
        except Exception:
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


async def broadcast_agent_status(event: dict) -> None:
    """Bridge agent status changes to WebSocket frontend clients."""
    try:
        agents_data = []
        for agent in agent_tracker.get_all_agents():
            agents_data.append({
                "agent_id": agent.agent_id,
                "agent_type": agent.agent_type.value,
                "status": agent.status.value,
                "current_task": agent.current_task_description or "",
                "task_count": agent.task_count,
                "error": agent.error or "",
            })
        await broadcast_to_ui({
            "type": "agent_update",
            "payload": {
                "agents": agents_data,
                "summary": agent_tracker.get_summary(),
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    except Exception as e:
        log.debug("broadcast_agent_status_skipped", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles backend startup and shutdown lifecycle events."""
    global _heartbeat_task
    log.info("jarvis_omega_backend_starting")

    # 1. Ensure storage directories exist
    settings.ensure_directories()

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
    agent_tracker.set_event_bus(event_bus)
    task_worker.setup(
        task_manager=task_manager,
        orchestrator=agent_orchestrator,
        agent_tracker=agent_tracker,
    )

    # Register task and WS message subscribers
    event_bus.subscribe(EventType.TASK_CREATED, dispatch_task_to_device)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_UPDATE.value}", handle_ws_task_update)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_RESULT.value}", handle_ws_task_result)
    event_bus.subscribe(EventType.TASK_STARTED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.TASK_COMPLETED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.TASK_FAILED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.AGENT_SPAWNED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.AGENT_FAILED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.AGENT_COMPLETED, agent_tracker.handle_task_event)
    event_bus.subscribe(EventType.TASK_STARTED, broadcast_agent_status)
    event_bus.subscribe(EventType.TASK_COMPLETED, broadcast_agent_status)
    event_bus.subscribe(EventType.TASK_FAILED, broadcast_agent_status)

    # 4. Initialize registries, graphs and engines
    await device_registry.initialize()
    await sqlite_memory.initialize()
    agent_tracker.initialize()
    log.info("agent_tracker_initialized", agent_count=len(agent_tracker.get_all_agents()))
    
    # Initialize V2 memory engine
    await memory_engine.initialize()
    
    # Skip project_graph initialization temporarily to isolate ChromaDB telemetry issue
    # try:
    #     await project_graph.initialize()
    # except Exception as e:
    #     log.error("project_graph_startup_failed", error=str(e))
    #     log.warning("project_graph_continuing_without", message="Project features may be limited")

    # Register components in health monitor
    health_monitor.register_component("WebSocketManager")
    health_monitor.register_component("Scheduler")
    health_monitor.register_component("MemoryEngine")
    health_monitor.register_component("TaskManager")
    health_monitor.register_component("Sentinel")
    health_monitor.register_component("TelegramBridge")
    health_monitor.register_component("DiscordBridge")
    health_monitor.register_component("WorkspaceWatcher")

    # 4b. Initialize Secure Vault
    secure_vault.initialize(settings.encryption_key)

    # 5. Start Background Services (non-blocking so server accepts connections immediately)
    asyncio.create_task(scheduler.start())
    asyncio.create_task(health_monitor.start())
    # Start memory indexer
    asyncio.create_task(memory_indexer.start())
    # Skip sentinel_service temporarily to isolate ChromaDB telemetry issue
    # asyncio.create_task(sentinel_service.start())
    # Skip workspace_watcher temporarily to isolate ChromaDB telemetry issue
    # asyncio.create_task(workspace_watcher.start())
    
    # Night Shift & Self-Improvement schedules
    asyncio.create_task(night_shift.register_schedules())
    asyncio.create_task(self_improvement.register_schedules())

    # Telegram bridge (only if token configured)
    asyncio.create_task(telegram_bridge.start())

    # Discord bridge (only if token configured)
    asyncio.create_task(discord_bridge.start())

    # Start automated failover watchdog
    asyncio.create_task(cron_failover.start())

    _heartbeat_task = asyncio.create_task(start_heartbeat_loop())
    task_worker.start()

    # Start 24/7 autonomous web scraper
    autonomous_scraper.start()

    # Start cursor overlay for visible desktop interactions
    try:
        from backend.services.desktop_cursor import cursor_overlay
        cursor_overlay.start()
        log.info("cursor_overlay_started")
    except Exception as e:
        log.debug("cursor_overlay_not_available", error=str(e))

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

    await task_worker.stop()
    await sqlite_memory.close()

    await memory_indexer.stop()
    await health_monitor.stop()
    # await sentinel_service.stop()  # Disabled since we're not starting it
    # await workspace_watcher.stop()  # Disabled since we're not starting it
    await telegram_bridge.stop()
    await autonomous_scraper.stop()
    await cron_failover.stop()
    await scheduler.stop()
    await browser_service.close()

    # Stop cursor overlay
    try:
        from backend.services.desktop_cursor import cursor_overlay
        cursor_overlay.stop()
    except Exception:
        pass

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

# Clerk verifier (strict mode for /api/* and /ws/*)
clerk_verifier: ClerkJWTVerifier | None = None
if settings.clerk_jwks_url and settings.clerk_issuer and settings.clerk_audience:
    clerk_verifier = ClerkJWTVerifier(
        ClerkVerificationConfig(
            jwks_url=settings.clerk_jwks_url,
            issuer=settings.clerk_issuer,
            audience=settings.clerk_audience,
            algorithms=tuple(settings.clerk_jwt_algorithms),
            clock_skew_seconds=settings.clerk_clock_skew_seconds,
        )
    )
    log.info(
        "clerk_verifier_initialized",
        jwks_url=bool(settings.clerk_jwks_url),
        issuer_set=bool(settings.clerk_issuer),
        audience_set=bool(settings.clerk_audience),
    )
else:
    log.warning(
        "clerk_verifier_not_configured",
        hint="Set CLERK_JWKS_URL, CLERK_ISSUER, CLERK_AUDIENCE in environment/.env."
    )


def _resolve_user_id(request: Request) -> str:
    """Clerk user id when authenticated; local dev fallback when Clerk is off."""
    clerk_claims = getattr(request.state, "clerk_claims", None)
    if clerk_claims and isinstance(clerk_claims, dict):
        return ClerkJWTVerifier.get_user_id_from_claims(clerk_claims)
    if not clerk_verifier:
        return "local-dev-user"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing clerk claims")


class ClerkAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            # Local dev: when Clerk is not configured, allow API access without JWT.
            if not clerk_verifier:
                return await call_next(request)

            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or not auth.lower().startswith("bearer "):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing Authorization Bearer token"},
                )
            token = auth.split(" ", 1)[1].strip()
            try:
                claims = await clerk_verifier.verify(token)
            except Exception as e:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": f"Invalid token: {str(e)}"},
                )
            request.state.clerk_claims = claims
        return await call_next(request)

# Apply middleware BEFORE mounting routers
app.add_middleware(ClerkAuthMiddleware)

# Include modular API routers (all /api/* is now protected by middleware)
app.include_router(router_chat)
app.include_router(router_openrouter)
app.include_router(router_groq)
app.include_router(router_audio)
app.include_router(router_vision)
app.include_router(router_shortcuts)
app.include_router(router_memory)
app.include_router(router_agents)
app.include_router(router_projects)
app.include_router(router_vault)
app.include_router(router_browser)
app.include_router(router_downloads)
app.include_router(router_settings)
app.include_router(router_media_generation)
app.include_router(router_agent_exec)
app.include_router(router_scheduler)
app.include_router(router_patterns)
app.include_router(router_mcp)
app.include_router(router_skills)
app.include_router(router_hardware)
app.include_router(router_tasks)
app.include_router(router_listening)
app.include_router(router_build)
app.include_router(router_clips)
app.include_router(router_mods)
app.include_router(router_connections)
app.include_router(router_focus)
app.include_router(router_social)


# ====================================================================
# REST API ENDPOINTS
# ====================================================================

# ---- New Pillar API Endpoints ----

@app.get("/api/sentinel/history", tags=["Sentinel"])
async def get_sentinel_history():
    return {"fixes": sentinel_service.get_fix_history()}

@app.get("/api/sentinel/health", tags=["Sentinel"])
async def get_sentinel_health():
    return {
        "sentinel_active": sentinel_service._running if hasattr(sentinel_service, '_running') else False,
        "last_fixes": len(sentinel_service.get_fix_history()),
    }

@app.get("/api/vision/sampler-stats", tags=["Vision"])
async def get_vision_sampler_stats():
    return dynamic_sampler.stats

@app.get("/api/research/briefing", tags=["Research"])
async def get_latest_briefing():
    brief = night_shift.get_last_briefing()
    if brief:
        return {"briefing": brief}
    return {"briefing": "No briefing generated yet. Night Shift runs daily at 06:00."}

@app.post("/api/research/trigger-briefing", tags=["Research"])
async def trigger_briefing():
    brief = await night_shift.generate_daily_briefing()
    return {"briefing": brief}

@app.get("/api/social/pending", tags=["Social"])
async def get_social_pending_drafts():
    return {"drafts": social_sentinel.get_pending_drafts()}

@app.post("/api/social/scan", tags=["Social"])
async def trigger_social_scan():
    results = await social_sentinel.scan_all()
    return results

@app.post("/api/social/approve/{index}", tags=["Social"])
async def approve_social_draft(index: int):
    success = social_sentinel.approve_draft(index)
    return {"approved": success}

@app.get("/api/improvement/lessons", tags=["Improvement"])
async def get_improvement_lessons():
    return {"lessons": self_improvement.get_lessons(), "stats": self_improvement.get_stats()}

@app.post("/api/improvement/analyze", tags=["Improvement"])
async def trigger_improvement_analysis():
    insights = await self_improvement.generate_insights()
    return {"insights": insights}

@app.post("/api/improvement/correction", tags=["Improvement"])
async def record_correction(user_message: str, correction: str):
    await self_improvement.record_correction(user_message, correction)
    return {"status": "recorded"}

@app.get("/api/telegram/status", tags=["Telegram"])
async def get_telegram_status():
    return {"running": telegram_bridge._running, "allowed_user": telegram_bridge._allowed_user_id is not None}

@app.get("/api/vault/status", tags=["Vault"])
async def get_vault_status():
    return {"initialized": True, "key_count": len(secure_vault.list_keys())}


@app.get("/health", tags=["System"])
async def get_health() -> Dict[str, Any]:
    """Returns the unified health status of the API and its subsystems."""
    return {
        "status": "online",
        "health": HealthState.DEGRADED.value,
        "scheduler_active": scheduler.job_count > 0 or scheduler._scheduler.running,
        "active_connections": ws_manager.connection_count,
        "tasks_in_queue": task_manager.queue_size,
        "sentinel_running": sentinel_service._running if hasattr(sentinel_service, '_running') else False,
        "telegram_running": telegram_bridge._running if hasattr(telegram_bridge, '_running') else False,
        "memory_engine_ok": False,
    }


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


@app.post("/api/devices/pair/generate", tags=["Devices"])
async def generate_pairing_qr(request: Request, desktop_device_id: str = Query(..., min_length=3)):
    """
    Generates a short-lived cross-device pairing payload suitable for QR encoding.

    Requires Clerk-authenticated request (enforced by middleware).
    Returns:
      - user_id
      - desktop_device_id
      - pairing_secret (high-entropy)
      - base_url
      - expires_at (unix seconds)
    """
    user_id = _resolve_user_id(request)

    try:
        pair = await device_registry.generate_pairing_payload(
            user_id=user_id,
            desktop_device_id=desktop_device_id,
        )
    except Exception as e:
        log.error("pair_generate_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate pairing token")

    return pair


@app.post("/api/devices/pair/register-desktop", tags=["Devices"])
async def register_desktop_companion(request: Request, body: DesktopRegisterRequest):
    """Register and trust a web/desktop companion device for the authenticated Clerk user."""
    user_id = _resolve_user_id(request)
    try:
        device = await device_registry.ensure_desktop_registered(
            user_id=user_id,
            desktop_device_id=body.desktop_device_id,
            device_name=body.device_name,
            platform=body.platform,
        )
    except Exception as e:
        log.error("desktop_register_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"device_id": device.device_id, "trusted": device.trusted}


@app.post("/api/devices/pair/consume", response_model=DevicePairingResponse, tags=["Devices"])
async def consume_qr_pairing(request: Request, body: QrPairConsumeRequest):
    """Complete QR cross-pairing from the Android app."""
    user_id = _resolve_user_id(request)
    try:
        return await device_registry.consume_pairing_payload(
            pairing_secret=body.pairing_secret,
            mobile_device_id=body.mobile_device_id,
            device_name=body.device_name,
            platform=body.platform,
            user_id=user_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.error("pair_consume_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pairing failed")


@app.get("/api/droid/devices", tags=["Droid"])
async def list_droid_devices():
    """List currently connected devices for dashboard status indicators."""
    connected = ws_manager.get_connected_devices()
    devices = []
    for entry in connected:
        dev = device_registry.get_device(entry.get("device_id", ""))
        devices.append(
            {
                "device_id": entry.get("device_id"),
                "device_name": entry.get("device_name") or (dev.device_name if dev else "Unknown"),
                "device_type": entry.get("device_type") or "unknown",
                "online": True,
            }
        )
    return {"devices": devices, "count": len(devices)}


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
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                raise
            except Exception as recv_err:
                log.warning("ui_ws_receive_error", error=str(recv_err))
                continue

            if not data or not data.strip():
                continue

            try:
                msg = orjson_parse(data)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type == "dispatch_command":
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
                try:
                    await websocket.send_json(
                        {"type": "error", "payload": {"message": "Invalid JSON message"}},
                    )
                except Exception:
                    pass

    except WebSocketDisconnect:
        _ui_clients.discard(websocket)
        log.info("ui_client_disconnected", total_ui_clients=len(_ui_clients))
    except Exception as e:
        _ui_clients.discard(websocket)
        log.error("ui_ws_error", error=str(e))


# ====================================================================
# DEVICE WEBSOCKET COMMAND & CONTROL TERMINAL
# ====================================================================

def device_name_from_id(device_id: str) -> str:
    """Human-friendly device name from a device_id."""
    if "phone" in device_id.lower() or "mobile" in device_id.lower() or "android" in device_id.lower():
        return f"Android Device ({device_id[:12]})"
    if "desktop" in device_id.lower() or "pc" in device_id.lower() or "laptop" in device_id.lower():
        return f"Desktop Client ({device_id[:12]})"
    return f"Device ({device_id[:12]})"


@app.websocket("/ws/{device_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    device_id: str,
    token: str = Query(None),
):
    """
    Main WebSocket bridge endpoint. Validates device access tokens,
    tracks health latency, and processes incoming messages.

    LOCAL DEV MODE: When Clerk is not configured (clerk_verifier is None),
    all WebSocket connections are accepted, devices are auto-registered as
    trusted, and no JWT verification is performed.  This allows the desktop
    daemon and Android app to connect without Clerk setup.
    """
    is_local_dev = clerk_verifier is None

    # 1. Access Token Verification (Clerk)
    if is_local_dev:
        log.info("ws_local_dev_accepting", device_id=device_id)
    else:
        if not token:
            log.warning("ws_rejected_no_token", device_id=device_id)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token required")
            return

        try:
            claims = await clerk_verifier.verify(token)
        except Exception as e:
            log.warning("ws_rejected_invalid_clerk_token", device_id=device_id, error=str(e))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
            return

    # 2. Device trust enforcement — auto-register on local dev
    if not device_registry.is_trusted(device_id):
        if is_local_dev:
            log.info("ws_local_dev_auto_register", device_id=device_id)
            await device_registry.ensure_desktop_registered(
                user_id="local-dev",
                desktop_device_id=device_id,
                device_name=device_name_from_id(device_id),
                platform="desktop",
            )
        else:
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
                # Prefer droid envelope routing if it matches the cross-device schema.
                # DROID envelopes are expected to carry: type (RESULT/NOTIFICATION), correlation_id, payload.
                # They may not conform to WSMessageType enum, so we handle them before WSMessage parsing.
                if isinstance(message_json, dict):
                    maybe_type = message_json.get("type")
                    if maybe_type in ("RESULT", "NOTIFICATION"):
                        await handle_droid_envelope(device_id=device_id, message=message_json)
                        continue

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


# Serve frontend static files (SPA + PWA assets) — must be LAST so API routes take priority
import os
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
    log.info("frontend_static_mounted", path=_frontend_dir)


def orjson_parse(data: str) -> Any:
    """Helper to parse JSON string using orjson."""
    import orjson
    return orjson.loads(data)
