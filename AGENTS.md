# AGENTS.md

Reference for AI agents (and humans pairing with them) working on this repo.

## Quick Start

```bash
# 1. Bootstrap secrets (the backend refuses to boot without these).
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste outputs as BACKEND_SECRET_KEY and ENCRYPTION_KEY in .env.

# 2. Install deps.
pip install -r requirements.txt

# 3. Run the full test suite.
python -m pytest backend/tests/ -v

# 4. Run the backend locally.
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## Commands You Will Be Asked To Run

| Task | Command |
|------|---------|
| **Lint** | `ruff check backend local_client shared` |
| **Type-check** | `mypy backend shared --ignore-missing-imports` |
| **Tests (fast)** | `python -m pytest backend/tests/ -x -q` |
| **Tests (with coverage)** | `python -m pytest backend/tests/ --cov=backend --cov=shared --cov-report=term-missing` |
| **Compile everything** | `python -m compileall -q backend local_client shared` |
| **Start backend** | `uvicorn backend.main:app --port 8000 --reload` |
| **Start local client** | `python local_client/daemon.py` |
| **Docker compose** | `docker compose up --build` |

Always run tests + lint after editing Python files. CI does this too.

## Repo Conventions

- **Python 3.12+**. Use modern typing (`dict[str, Any]`, `X | None`).
- **No `shell=True` in subprocess calls.** Use explicit argv.
- **No `except Exception: pass`.** Catch specific exceptions or log.
- **No hardcoded secrets.** All secrets live in `.env` (gitignored). The
  startup validator in `backend/config.py:validate_security_settings` will
  refuse to boot if `BACKEND_SECRET_KEY` or `ENCRYPTION_KEY` is missing.
- **Test fixtures** in `conftest.py` set deterministic test-only bootstrap
  secrets so the security module initializes correctly under pytest.

## Architecture Quick Map

```
backend/         FastAPI app
  main.py        Lifespan, REST routes, two WS endpoints (/ws/ui + /ws/{device_id})
  routers/       REST routers (chat, agents, memory, projects, …)
  services/      LLM, TTS, command-safety, command-interpreter, memory
  approval_gateway.py  Human-in-the-loop gate
  device_registry.py   Pairing + trust state
  memory_engine.py     ChromaDB vector store
  scheduler.py         APScheduler wrapper
  websocket_manager.py Device WS hub
local_client/    Workstation daemon
  daemon.py      Boot order, signal handling
  agents/        15 specialized agents
  websocket_client.py  Connects to backend /ws/{device_id}
shared/          Pydantic models, constants, security utils, logging
config/          Runtime config templates (placeholders only — never real secrets)
frontend/        Static HTML dashboard
```

The `src/` directory contains a deprecated TypeScript daemon. Do NOT edit it
unless explicitly asked — it's cold storage.

## Safety-Critical Files

If you edit any of these, run the FULL test suite and double-check your
work — they're load-bearing for system integrity:

- `backend/services/command_safety.py` — the RCE-prevention validator.
- `shared/constants.py:DANGEROUS_COMMAND_PATTERNS` /
  `BLOCKED_COMMAND_PATTERNS` — the pattern tables.
- `backend/approval_gateway.py` — the human-approval flow.
- `shared/security.py` — JWT, Fernet, password hashing.
- `backend/config.py:validate_security_settings` — fail-fast at startup.
- `backend/routers/router_chat.py:_dispatch_and_wait` — the only place
  shell commands actually execute.

## Known Quirks

- On Windows, `websockets` library auto-detects the right event loop policy.
  If you see `RuntimeError: Event loop is closed`, set
  `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
  at the top of `daemon.py`.
- `chromadb` logs a noisy `capture() takes 1 positional argument but 3 were
  given` telemetry warning. It's a ChromaDB internal bug, not ours — ignored.
- The `frontend/index.html` uses `innerHTML` on LLM output, which is an XSS
  vector. Tracked as a known issue; do not surface LLM output as HTML
  without escaping.
