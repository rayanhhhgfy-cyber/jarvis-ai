# Architecture

This document describes how JARVIS OMEGA is wired together at the module
level. It's intended for contributors who need to know where to plug a new
feature in.

## High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                       Frontend dashboard                          │
│                  (static HTML at frontend/index.html)             │
└──────────────────────────────┬───────────────────────────────────┘
                               │ WS /ws/ui  (unauthenticated, local)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                          FastAPI backend                          │
│                                                                   │
│  ┌────────────┐  ┌─────────────┐  ┌────────────┐  ┌───────────┐  │
│  │ routers/   │  │ services/   │  │ approval_  │  │ device_   │  │
│  │ chat,mem,… │→ │ llm, tts,…  │  │ gateway    │  │ registry  │  │
│  └────────────┘  └─────────────┘  └────────────┘  └───────────┘  │
│         │              │              ▲                ▲          │
│         ▼              ▼              │                │          │
│  ┌────────────┐  ┌─────────────┐     │                │          │
│  │ command_   │  │ memory_     │     │                │          │
│  │ safety     │  │ engine      │     │                │          │
│  └────────────┘  └─────────────┘     │                │          │
│         │                              │                │          │
│         ▼                              │                │          │
│  ┌──────────────────────────────────────────────────┐ │          │
│  │ _dispatch_and_wait — the ONLY shell-execution    │ │          │
│  │ site in the system. Every command flows here.    │─┘          │
│  └──────────────────────────────────────────────────┘            │
│                              │                                    │
│  event_bus ─────────────────┐│                                    │
│  scheduler (APScheduler)    ││                                    │
│  health_monitor             ▼│                                    │
│  ws_manager ◄────────────────┘                                    │
└──────────────────────────────┬───────────────────────────────────┘
                               │ WS /ws/{device_id} (JWT-verified)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Local client daemon                         │
│                                                                   │
│  daemon.py boots in dependency order:                             │
│    1. state_manager      loads config/client_config.json          │
│    2. websocket_client   persistent WS to backend                 │
│    3. health_reporter    pushes CPU/mem stats                     │
│    4. clipboard_manager  cross-device clipboard sync              │
│    5. filesystem_watcher workspace change events                  │
│    6. microphone_listener VAD + STT                               │
│    7. wakeword_detector  "jarvis" hotword                         │
│    8. task_executor      receives EXECUTE_TASK messages           │
│                                                                   │
│  agents/ contains 15 specialized agents loaded dynamically by     │
│  the orchestrator via importlib.import_module().                  │
└──────────────────────────────────────────────────────────────────┘
```

## Boot Order

`backend/main.py:lifespan` does the following on startup:

1. `settings.ensure_directories()` — create storage/logs/memory/cache.
2. `settings.validate_security_settings()` — fail fast on missing secrets.
3. `init_security(...)` — populate JWT signing key + Fernet key.
4. Wire up event-bus dependencies between ws_manager, device_registry,
   approval_gateway, task_manager, health_monitor.
5. Subscribe task-creation and approval-event handlers to the event bus.
6. `device_registry.initialize()` — load `storage/devices.json` and log
   the trust snapshot (makes the WebSocket 403 case observable).
7. `memory_engine.initialize()` — open ChromaDB persistent client.
8. `project_graph.initialize()` — load project graph.
9. Register components in health_monitor.
10. Start background services: scheduler, health_monitor, memory_indexer,
    heartbeat loop.
11. Ready.

## The Two WebSocket Endpoints

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `WS /ws/ui` | None (local LAN only) | Frontend dashboard — proactive reports, approval requests, system status. |
| `WS /ws/{device_id}?token=…` | JWT verified + device_registry.is_trusted | Local client daemon — bidirectional command/result channel. |

UI clients are tracked in `_ui_clients` in `main.py`. Devices are tracked in
`ws_manager._connections`. The approval gateway broadcasts to BOTH — to
devices via `ws_manager.broadcast` and to UI via the
`handle_approval_event` event-bus subscriber.

## Agent Hierarchy

All 15 agents share a common skeleton:

```python
class AgentX:
    agent_id = "agent_x"
    agent_type = AgentType.X

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        action = task.payload.get("action", "<default>")
        # dispatch on action...
```

The orchestrator (`local_client/agents/agent_orchestrator.py`) decomposes a
goal into subtasks (via `agent_planner`), fans them out to the appropriate
agents, retries failures, and on permanent failure invokes `agent_repair`
for diagnosis.

### Agent roster

| Agent | Phase 4 status |
|-------|----------------|
| `agent_orchestrator` | Original (unchanged) |
| `agent_planner` | **Real LLM-driven decomposition** with template fallback |
| `agent_security` | **Real regex-based secret scanner** (AWS/OpenRouter/GitHub/Slack/Stripe/PEM/etc.) |
| `agent_memory` | **Real ChromaDB archival/pruning** + log cleanup |
| `agent_vision` | **Real Qwen 2.5 VL OCR** via OpenRouter |
| `agent_repair` | **Structured traceback parser** + heuristic fix proposals |
| `agent_testing` | **Structured pytest result parser** |
| `agent_code` | Original |
| `agent_os` | Original |
| `agent_browser` | Original (Playwright) |
| `agent_video` | Original (OpenCV) |
| `agent_deployment` | Original |
| `agent_monitor` | Original |
| `agent_document` | Original |
| `agent_research` | Original |

## Command Execution Flow

This is the load-bearing path for the whole system. Read it carefully.

```
User message
   │
   ▼
router_chat.process_chat
   │
   ├─► command_interpreter.interpret(message)  ─► [(description, cmd), ...]
   │       for each: _dispatch_and_wait(cmd)
   │
   └─► run_tool_loop(message, history, results)
          │
          ├─► llm_service.get_response(...)
          │       may emit <run_os_command>…</run_os_command> tags
          │
          └─► _dispatch_and_wait(cmd)  ← this is the ONLY shell-exec site
                  │
                  ├─► command_safety.validate(cmd)
                  │       ├─ ALLOWED       → proceed
                  │       ├─ NEEDS_APPROVAL → approval_gateway.request + wait
                  │       └─ BLOCKED       → return early, log, no exec
                  │
                  └─► subprocess.Popen(["cmd","/c",cmd], shell=False)
                          (or ["/bin/sh","-c",cmd] on POSIX)
```

Three independent safety layers stack:

1. Pattern tables in `shared/constants.py`.
2. Validator in `backend/services/command_safety.py`.
3. Human approval in `backend/approval_gateway.py`.

## Memory Engine

ChromaDB-backed vector store. Every `MemoryCategory` is a separate
collection. The memory_indexer runs in the background and indexes new
memory entries for semantic search.

```
MemoryEntry ──► memory_engine.store()
                      │
                      ▼
              ChromaDB collection (one per MemoryCategory)
                      │
                      ▼
              memory_engine.query(MemoryQuery) ─► List[MemoryEntry]
                      │
                      ▼
              llm_service._format_memory_context(MemoryContext)
                      │
                      ▼
              injected into the LLM system context
```

## Tool Registry (Phase 8 — in progress)

The current `<run_os_command>` tag-based tool interface is being replaced
with a proper function-calling substrate. When complete:

- `backend/tools/registry.py` holds a `@tool` decorator and a process-wide
  `ToolRegistry`.
- Every tool declares a JSON schema for its arguments and a `RiskTier`.
- The LLM is invoked with the full list of tool schemas (native
  function-calling on OpenRouter/OpenAI).
- `backend/tools/executor.py` dispatches tool calls, enforces the risk tier,
  and remembers per-session approval decisions.
- Existing 15 agents become plugins under `plugins/`.

Capability tiers:

| Tier | Example tools | Approval rule |
|------|---------------|---------------|
| 0 — Observe | `files.read`, `files.search`, `web.search` | Always allowed |
| 1 — Reversible | `files.write` in workspace, `git.commit` | Allowed + logged |
| 2 — System | `shell.run` (install), `process.kill`, `app.open` | Ask once per tool |
| 3 — Destructive | `files.delete`, `format.drive`, `net.modify` | Always ask |
| 4 — External | `email.send`, `slack.post`, `payment.send` | Always ask + 2FA |

## What lives where

| Concern | File / dir |
|---------|-----------|
| FastAPI app + lifespan | `backend/main.py` |
| REST routers | `backend/routers/router_*.py` |
| LLM (OpenRouter) | `backend/services/llm_service.py` |
| Memory (ChromaDB) | `backend/memory_engine.py` |
| Device pairing + trust | `backend/device_registry.py` |
| Approval flow | `backend/approval_gateway.py` |
| Command validator | `backend/services/command_safety.py` |
| WS hub (devices) | `backend/websocket_manager.py` |
| WS hub (UI) | `backend/main.py:_ui_clients` |
| Cron / interval jobs | `backend/scheduler.py` |
| Pydantic models | `shared/models.py` |
| Enums + pattern tables | `shared/constants.py` |
| JWT / Fernet / signatures | `shared/security.py` |
| Structured logging | `shared/logger.py` |
| Local daemon | `local_client/daemon.py` |
| Local WS client | `local_client/websocket_client.py` |
| Agents | `local_client/agents/agent_*.py` |

## Testing Strategy

`backend/tests/` holds 110+ tests across:

- `test_main.py`, `test_config.py`, `test_models.py` — baseline smoke tests.
- `test_security.py` — JWT, Fernet, HMAC, password hashing, plus the
  Phase 1 regression that init_security rejects placeholder keys.
- `test_chat_safety.py` — the command validator (parametrized over
  ALLOWED / NEEDS_APPROVAL / BLOCKED commands).
- `test_approval_gateway.py` — request lifecycle, approve/reject/timeout.
- `test_device_registry.py` — pairing + trust persistence across simulated
  restart (the WS 403 regression).
- `test_memory_engine.py` — ChromaDB round-trip with a tmp persist dir.
- `test_scheduler.py` — interval and cron scheduling, cancel, job_count.
- `test_agents.py` — parametrized tests for security, planner, repair,
  testing agents.
- `test_orchestrator.py`, `test_react_loop.py`, `test_command_interpreter.py`
  — original tests, unchanged.

`conftest.py` sets deterministic bootstrap secrets in the environment before
any test imports the app, and autouse-initializes the security module.

## Known Limitations

- The static `frontend/index.html` uses `innerHTML` on LLM output (XSS risk).
- `src/` contains a parallel TypeScript daemon that is NOT wired in.
- Audio/video/screenshot subsystems degrade gracefully when their native
  dependencies are missing (sounddevice, mss, opencv).
- The Docker container cannot use audio/screenshot/microphone subsystems —
  those run in the local client daemon on the host.
