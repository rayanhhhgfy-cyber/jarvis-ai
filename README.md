# J.A.R.V.I.S. Omega

AI-driven multi-agent system with FastAPI backend, Next.js frontend, and cross-device support.

## Boot Order

### 1. Prerequisites
- Python 3.10+
- Node.js 18+
- Microsoft Edge (for Playwright browser automation)
- Termux (Samsung A31 / Android deployment)

### 2. API Keys (.env)
```
OPENROUTER_API_KEY_01=sk-or-v1-...
... (11 keys for rotation)
OPENROUTER_API_KEY_11=sk-or-v1-...

GROQ_API_KEY=gsk_...

REPLICATE_API_KEY=r8_...

# Optional
SUPABASE_URL=
SUPABASE_API_KEY=
CLERK_JWKS_URL=
CLERK_ISSUER=
CLERK_AUDIENCE=
```

### 3. Install Dependencies
```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install

# Playwright browser
playwright install chromium
```

### 4. Start Backend
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start Frontend
```bash
cd frontend && npm run dev
```

### 6. Start Desktop Daemon
```bash
.\Start-Jarvis-Desktop.bat
```

## Architecture

```
backend/
├── main.py                 # FastAPI entry point + lifespan
├── config.py               # Settings (LAN IP, keys, etc.)
├── routers/                # REST API endpoints
│   ├── router_chat.py      # Main chat + command execution
│   ├── router_agents.py    # Agent status monitoring
│   ├── router_agent_exec.py# Sub-agent task execution
│   ├── router_scheduler.py # APScheduler + goal execution
│   ├── router_patterns.py  # Pattern detection + workflows
│   ├── router_hardware.py  # WoL, termux-notification
│   ├── router_skills.py    # Skill install/execute
│   ├── router_mcp.py       # MCP server management
│   └── ...
├── services/               # All business logic
│   ├── llm_service.py      # OpenRouter key rotation
│   ├── browser_service.py  # Playwright browser control
│   ├── desktop_service.py  # Mouse/keyboard/window
│   ├── web_search_service.py
│   ├── excel_service.py
│   ├── media_generation_service.py
│   ├── system_pulse.py     # psutil monitoring
│   ├── lazarus_sentry.py   # Self-resurrection
│   ├── pentest_sentry.py   # Self-audit
│   ├── network_sentry.py   # LAN scanner
│   ├── guardrail_shield.py # Rate limit + injection
│   ├── phantom_browser.py  # Anti-detection browser
│   ├── crypt_vault.py      # AES-256-GCM vault
│   ├── sound_engine.py     # TTS + tone alerts
│   ├── recovery_engine.py  # Auto-debug + NVD watcher
│   ├── goal_executor.py    # Iterative goal execution
│   ├── skill_manager.py    # Dynamic skill loader
│   └── ...
├── memory/
│   └── sqlite_memory.py    # SQLite vector memory
└── droid/                  # Cross-device messaging
```

## Key Features
- **Desktop Control**: Mouse, keyboard, windows, clipboard, screenshots
- **Browser Automation**: Persistent Playwright with Edge channel
- **Web Search**: DuckDuckGo Lite, URL fetch, Maps search
- **File Operations**: Download, Excel creation, media generation
- **Goal Execution**: Iterative LLM-driven command sequences
- **Pattern Detection**: Auto-suggest workflows from command history
- **Cross-Device**: WebSocket bridge between desktop/phone
- **Voice**: TTS responses + sound alerts (pyttsx3/espeak)
- **Media Generation**: OpenRouter images, Replicate videos
- **Skill System**: Dynamic Python module installation/execution
- **MCP Server**: JSON-RPC over HTTP tool execution

## Ports
- `8000` — Backend API
- `3000` — Next.js frontend
- `8001` — Parallel testing

## TERMUX-NOTE
All Android-specific fallbacks annotated with `# TERMUX-NOTE:` in source.
- scapy → nmap subprocess
- openai-whisper → Groq Whisper API
- DMI serial → MAC + hostname key derivation
- pyttsx3 → termux-tts-speak fallback
