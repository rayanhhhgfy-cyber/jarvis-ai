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
from backend.proactive_watcher import proactive_watcher

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
    router_omega,
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

from backend.ui_manager import ui_manager

async def broadcast_to_ui(message: dict) -> None:
    """Compatibility wrapper for ui_manager.broadcast."""
    await ui_manager.broadcast(message)


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

    # Register task and WS message subscribers
    event_bus.subscribe(EventType.TASK_CREATED, dispatch_task_to_device)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_UPDATE.value}", handle_ws_task_update)
    event_bus.subscribe(f"ws_msg_{WSMessageType.TASK_RESULT.value}", handle_ws_task_result)

    # 4. Initialize registries, graphs and engines
    await device_registry.initialize()
    await memory_engine.initialize()
    await project_graph.initialize()

    # Register components in health monitor
    health_monitor.register_component("WebSocketManager")
    health_monitor.register_component("Scheduler")
    health_monitor.register_component("MemoryEngine")
    health_monitor.register_component("TaskManager")

    # 5. Start Background Services
    await scheduler.start()
    await health_monitor.start()
    await memory_indexer.start()
    await proactive_watcher.start()
    _heartbeat_task = asyncio.create_task(start_heartbeat_loop())

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

    await proactive_watcher.stop()
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
app.include_router(router_omega)


# ====================================================================
# REST API ENDPOINTS
# ====================================================================

@app.get("/health", tags=["System"])
async def get_health() -> Dict[str, Any]:
    """Returns the unified health status of the API and its subsystems."""
    db_ok = True
    # Basic check for memory engine collections
    try:
        stats = await memory_engine.get_stats()
        memory_ok = len(stats) > 0
    except Exception:
        memory_ok = False

    return {
        "status": "online",
        "health": HealthState.HEALTHY.value if (db_ok and memory_ok) else HealthState.DEGRADED.value,
        "scheduler_active": scheduler.job_count > 0 or scheduler._scheduler.running,
        "active_connections": ws_manager.connection_count,
        "tasks_in_queue": task_manager.queue_size,
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
    ui_manager.add_client(websocket)
    log.info("ui_client_connected", total_ui_clients=ui_manager.client_count)

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
        ui_manager.remove_client(websocket)
        log.info("ui_client_disconnected", total_ui_clients=ui_manager.client_count)
    except Exception as e:
        ui_manager.remove_client(websocket)
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
