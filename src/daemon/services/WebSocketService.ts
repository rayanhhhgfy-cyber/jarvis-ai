import { createLogger } from "../../utils/logger";
import type { Service } from "../ServiceRegistry";
import type { ConfigManager } from "../../config/ConfigManager";
import type { AgentOrchestrator } from "../../agents/AgentOrchestrator";

const log = createLogger("websocket");

interface WSClient {
  id: string;
  send: (data: string) => void;
  close: () => void;
}

export class WebSocketService implements Service {
  name = "websocket";
  private configManager: ConfigManager;
  private agentOrchestrator: AgentOrchestrator;
  private clients: Map<string, WSClient> = new Map();
  private server: any = null;
  private running = false;
  private agentId: string | null = null;

  constructor(configManager: ConfigManager, agentOrchestrator: AgentOrchestrator) {
    this.configManager = configManager;
    this.agentOrchestrator = agentOrchestrator;
  }

  async start(): Promise<void> {
    const port = this.configManager.get<number>("websocket.port") || 3142;
    const host = this.configManager.get<string>("websocket.host") || "0.0.0.0";

    // Get agent ID from the agent service
    const agentService = (globalThis as Record<string, unknown>).__agentService as { getAgentId: () => string | null } | undefined;
    this.agentId = agentService?.getAgentId() || null;

    log.info(`WebSocket server starting on ${host}:${port}`);

    // HTTP + WS server using Bun
    this.server = Bun.serve({
      hostname: host,
      port,
      fetch: async (req, server) => {
        const url = new URL(req.url);

        // WebSocket upgrade
        if (server.upgrade(req)) {
          return;
        }

        // HTTP API routes
        if (url.pathname === "/api/health") {
          return new Response(JSON.stringify({
            status: "ok",
            uptime: process.uptime(),
            clients: this.clients.size,
            agent: this.agentId ? "initialized" : "not_initialized",
          }), {
            headers: { "Content-Type": "application/json" },
          });
        }

        if (url.pathname === "/api/chat" && req.method === "POST") {
          try {
            const body = await req.json() as { message: string; agentId?: string };
            const agentId = body.agentId || this.agentId;
            if (!agentId) {
              return new Response(JSON.stringify({ error: "Agent not initialized" }), { status: 400, headers: { "Content-Type": "application/json" } });
            }
            const response = await this.agentOrchestrator.processMessage(agentId, body.message);
            return new Response(JSON.stringify({ response }), {
              headers: { "Content-Type": "application/json" },
            });
          } catch (err) {
            return new Response(JSON.stringify({ error: (err as Error).message }), { status: 500, headers: { "Content-Type": "application/json" } });
          }
        }

        if (url.pathname === "/api/sub-agents") {
          return new Response(JSON.stringify(this.agentOrchestrator.listSubAgents()), {
            headers: { "Content-Type": "application/json" },
          });
        }

        if (url.pathname === "/api/approvals" && req.method === "GET") {
          const approvals = this.agentOrchestrator.getToolExecutor().getPendingApprovals();
          return new Response(JSON.stringify(approvals), {
            headers: { "Content-Type": "application/json" },
          });
        }

        if (url.pathname === "/api/approvals/resolve" && req.method === "POST") {
          try {
            const body = await req.json() as { id: string; approved: boolean };
            const resolved = this.agentOrchestrator.getToolExecutor().resolveApproval(body.id, body.approved);
            return new Response(JSON.stringify({ resolved }), {
              headers: { "Content-Type": "application/json" },
            });
          } catch (err) {
            return new Response(JSON.stringify({ error: (err as Error).message }), { status: 500, headers: { "Content-Type": "application/json" } });
          }
        }

        // Dashboard UI (service info)
        if (url.pathname === "/") {
          return new Response(this.getDashboardHTML(), {
            headers: { "Content-Type": "text/html" },
          });
        }

        return new Response("Not Found", { status: 404 });
      },
      websocket: {
        open: (ws) => {
          const id = crypto.randomUUID();
          const client: WSClient = {
            id,
            send: (data: string) => ws.send(data),
            close: () => ws.close(),
          };
          this.clients.set(id, client);
          log.info(`WebSocket client connected: ${id}`);
          ws.send(JSON.stringify({ type: "connected", clientId: id }));
        },
        message: async (ws, message) => {
          try {
            const data = JSON.parse(message as string) as { type: string; payload: Record<string, unknown> };

            switch (data.type) {
              case "chat": {
                if (!this.agentId) {
                  ws.send(JSON.stringify({ type: "error", payload: { message: "Agent not initialized" } }));
                  return;
                }
                const response = await this.agentOrchestrator.processMessage(
                  this.agentId,
                  data.payload.message as string,
                );
                ws.send(JSON.stringify({ type: "response", payload: { response } }));
                break;
              }
              case "approve": {
                const resolved = this.agentOrchestrator.getToolExecutor().resolveApproval(
                  data.payload.id as string,
                  data.payload.approved as boolean,
                );
                ws.send(JSON.stringify({ type: "approval-result", payload: { resolved } }));
                break;
              }
              default:
                ws.send(JSON.stringify({ type: "error", payload: { message: `Unknown message type: ${data.type}` } }));
            }
          } catch (err) {
            ws.send(JSON.stringify({ type: "error", payload: { message: (err as Error).message } }));
          }
        },
        close: (ws) => {
          for (const [id, client] of this.clients) {
            if (client.close === ws.close) {
              this.clients.delete(id);
              log.info(`WebSocket client disconnected: ${id}`);
              break;
            }
          }
        },
      },
    });

    this.running = true;
    log.info(`WebSocket server running on http://${host}:${port}`);
  }

  async stop(): Promise<void> {
    if (this.server) {
      this.server.stop();
      this.server = null;
    }
    for (const [, client] of this.clients) {
      client.close();
    }
    this.clients.clear();
    this.running = false;
    log.info("WebSocket service stopped");
  }

  isRunning(): boolean {
    return this.running;
  }

  setAgentId(id: string): void {
    this.agentId = id;
  }

  broadcast(data: Record<string, unknown>): void {
    const msg = JSON.stringify(data);
    for (const [, client] of this.clients) {
      try {
        client.send(msg);
      } catch {
        // Client might be disconnected
      }
    }
  }

  private getDashboardHTML(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>J.A.R.V.I.S. — Omega</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  @keyframes scanline {
    0% { transform: translateY(-100%); }
    100% { transform: translateY(100vh); }
  }
  @keyframes glow {
    0%, 100% { text-shadow: 0 0 10px #00d4ff, 0 0 20px #00d4ff, 0 0 40px #00d4ff; }
    50% { text-shadow: 0 0 5px #00d4ff, 0 0 10px #00d4ff, 0 0 20px #00d4ff; }
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes typing {
    from { width: 0; }
    to { width: 100%; }
  }
  @keyframes blink {
    0%, 100% { border-right-color: transparent; }
    50% { border-right-color: #00d4ff; }
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: #050510;
    color: #c0d0e0;
    font-family: 'Share Tech Mono', monospace;
    height: 100vh;
    overflow: hidden;
    position: relative;
  }

  /* Scanline overlay */
  body::after {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0, 212, 255, 0.015) 2px,
      rgba(0, 212, 255, 0.015) 4px
    );
    pointer-events: none;
    z-index: 999;
  }

  /* Grid background */
  .grid-bg {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image:
      linear-gradient(rgba(0, 212, 255, 0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 212, 255, 0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  /* Central HUD ring */
  .hud-ring {
    position: fixed;
    top: 50%; left: 50%;
    width: 600px; height: 600px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 1px solid rgba(0, 212, 255, 0.05);
    pointer-events: none;
    z-index: 0;
  }
  .hud-ring-inner {
    position: fixed;
    top: 50%; left: 50%;
    width: 400px; height: 400px;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 1px solid rgba(0, 212, 255, 0.03);
    pointer-events: none;
    z-index: 0;
  }

  .container {
    display: flex;
    height: 100vh;
    position: relative;
    z-index: 1;
  }

  /* Sidebar — HUD Panel */
  .sidebar {
    width: 260px;
    background: rgba(5, 5, 20, 0.95);
    border-right: 1px solid rgba(0, 212, 255, 0.2);
    padding: 24px 20px;
    display: flex;
    flex-direction: column;
    backdrop-filter: blur(10px);
  }

  .jarvis-logo {
    text-align: center;
    margin-bottom: 32px;
    position: relative;
  }

  .jarvis-logo .icon {
    width: 60px; height: 60px;
    margin: 0 auto 12px;
    border: 2px solid #00d4ff;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    animation: glow 3s ease-in-out infinite;
  }
  .jarvis-logo .icon::before {
    content: '';
    position: absolute;
    width: 70px; height: 70px;
    border: 1px solid rgba(0, 212, 255, 0.3);
    border-radius: 50%;
    animation: spin 8s linear infinite;
  }
  .jarvis-logo .icon::after {
    content: '';
    position: absolute;
    width: 50px; height: 50px;
    border: 1px dashed rgba(0, 212, 255, 0.2);
    border-radius: 50%;
    animation: spin 6s linear infinite reverse;
  }
  .jarvis-logo .icon svg {
    position: relative;
    z-index: 1;
  }

  .jarvis-logo h1 {
    font-family: 'Orbitron', sans-serif;
    font-size: 16px;
    font-weight: 700;
    color: #00d4ff;
    letter-spacing: 6px;
    text-transform: uppercase;
    animation: glow 3s ease-in-out infinite;
  }
  .jarvis-logo .sub {
    font-size: 9px;
    color: rgba(0, 212, 255, 0.5);
    letter-spacing: 8px;
    text-transform: uppercase;
    margin-top: 4px;
  }

  .hud-section {
    margin-bottom: 20px;
  }
  .hud-section-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 9px;
    color: rgba(0, 212, 255, 0.6);
    letter-spacing: 3px;
    text-transform: uppercase;
    border-bottom: 1px solid rgba(0, 212, 255, 0.1);
    padding-bottom: 6px;
    margin-bottom: 10px;
  }

  .stat-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    font-size: 11px;
  }
  .stat-row .label { color: rgba(192, 208, 224, 0.5); }
  .stat-row .value { color: #00d4ff; }

  .status-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(0, 212, 255, 0.05);
    border: 1px solid rgba(0, 212, 255, 0.15);
    border-radius: 4px;
    margin-bottom: 8px;
  }
  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #00ff88;
    box-shadow: 0 0 8px #00ff88;
    animation: pulse 2s ease-in-out infinite;
  }
  .status-dot.warning { background: #ffaa00; box-shadow: 0 0 8px #ffaa00; }
  .status-dot.error { background: #ff3344; box-shadow: 0 0 8px #ff3344; }

  .status-text {
    font-size: 11px;
    color: #00ff88;
    letter-spacing: 1px;
  }

  /* Quick actions */
  .quick-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .quick-btn {
    padding: 8px;
    font-family: 'Share Tech Mono', monospace;
    font-size: 9px;
    background: rgba(0, 212, 255, 0.05);
    border: 1px solid rgba(0, 212, 255, 0.15);
    border-radius: 4px;
    color: rgba(192, 208, 224, 0.7);
    cursor: pointer;
    transition: all 0.2s;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .quick-btn:hover {
    background: rgba(0, 212, 255, 0.15);
    border-color: #00d4ff;
    color: #00d4ff;
    box-shadow: 0 0 10px rgba(0, 212, 255, 0.2);
  }

  /* Main panel */
  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: rgba(5, 5, 16, 0.8);
  }

  .top-bar {
    padding: 12px 24px;
    border-bottom: 1px solid rgba(0, 212, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
  }
  .top-bar .status-line {
    color: rgba(0, 212, 255, 0.6);
    letter-spacing: 1px;
  }
  .top-bar .status-line .highlight {
    color: #00d4ff;
  }

  .top-bar .title {
    font-family: 'Orbitron', sans-serif;
    font-size: 11px;
    color: rgba(0, 212, 255, 0.4);
    letter-spacing: 4px;
  }

  .chat-area {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    scroll-behavior: smooth;
  }
  .chat-area::-webkit-scrollbar {
    width: 4px;
  }
  .chat-area::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.3);
  }
  .chat-area::-webkit-scrollbar-thumb {
    background: rgba(0, 212, 255, 0.3);
    border-radius: 2px;
  }

  .msg {
    margin-bottom: 16px;
    padding: 14px 18px;
    border-radius: 6px;
    max-width: 85%;
    animation: fadeIn 0.3s ease-out;
    position: relative;
    line-height: 1.6;
    font-size: 13px;
  }

  .msg.user {
    background: rgba(0, 100, 180, 0.1);
    border: 1px solid rgba(0, 150, 255, 0.15);
    margin-left: auto;
    border-right: 2px solid #0096ff;
  }
  .msg.user::before {
    content: '>';
    color: #0096ff;
    margin-right: 8px;
    font-family: 'Orbitron', sans-serif;
    font-size: 11px;
  }

  .msg.assistant {
    background: rgba(0, 212, 255, 0.03);
    border: 1px solid rgba(0, 212, 255, 0.1);
    border-left: 2px solid #00d4ff;
    margin-right: auto;
  }

  .msg.system {
    background: rgba(255, 170, 0, 0.05);
    border: 1px solid rgba(255, 170, 0, 0.15);
    border-left: 2px solid #ffaa00;
    margin: 0 auto;
    max-width: 70%;
    text-align: center;
    font-size: 11px;
  }

  .msg .role-tag {
    font-family: 'Orbitron', sans-serif;
    font-size: 8px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 6px;
    opacity: 0.6;
  }
  .msg.user .role-tag { color: #0096ff; }
  .msg.assistant .role-tag { color: #00d4ff; }
  .msg.system .role-tag { color: #ffaa00; }

  .msg .text { white-space: pre-wrap; word-break: break-word; }

  .msg.assistant .text .typing-cursor {
    display: inline-block;
    width: 8px;
    height: 14px;
    background: #00d4ff;
    margin-left: 2px;
    animation: blink 0.8s step-end infinite;
  }

  /* Input area */
  .input-area {
    padding: 16px 24px;
    border-top: 1px solid rgba(0, 212, 255, 0.1);
    display: flex;
    gap: 12px;
    align-items: center;
    background: rgba(5, 5, 16, 0.9);
  }

  .input-area .prompt {
    font-family: 'Orbitron', sans-serif;
    font-size: 11px;
    color: #00d4ff;
    letter-spacing: 2px;
    opacity: 0.7;
  }

  .input-area input {
    flex: 1;
    padding: 12px 16px;
    border-radius: 4px;
    border: 1px solid rgba(0, 212, 255, 0.2);
    background: rgba(0, 0, 0, 0.5);
    color: #00d4ff;
    font-family: 'Share Tech Mono', monospace;
    font-size: 13px;
    outline: none;
    transition: all 0.2s;
  }
  .input-area input:focus {
    border-color: #00d4ff;
    box-shadow: 0 0 15px rgba(0, 212, 255, 0.1);
  }
  .input-area input::placeholder {
    color: rgba(0, 212, 255, 0.2);
  }

  .input-area button {
    padding: 12px 28px;
    background: transparent;
    border: 1px solid #00d4ff;
    border-radius: 4px;
    color: #00d4ff;
    font-family: 'Orbitron', sans-serif;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.3s;
  }
  .input-area button:hover {
    background: rgba(0, 212, 255, 0.1);
    box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
  }
  .input-area button:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  /* Thinking indicator */
  .thinking {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    font-size: 11px;
    color: rgba(0, 212, 255, 0.5);
    letter-spacing: 2px;
    margin-bottom: 12px;
  }
  .thinking .dots span {
    display: inline-block;
    width: 4px; height: 4px;
    background: #00d4ff;
    border-radius: 50%;
    margin: 0 2px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  .thinking .dots span:nth-child(2) { animation-delay: 0.3s; }
  .thinking .dots span:nth-child(3) { animation-delay: 0.6s; }

  /* Tool call display */
  .tool-call {
    font-size: 10px;
    color: rgba(0, 212, 255, 0.4);
    padding: 4px 12px;
    margin: 4px 0 8px;
    border-left: 2px solid rgba(0, 212, 255, 0.15);
    font-family: 'Share Tech Mono', monospace;
  }
  .tool-call .name { color: rgba(0, 212, 255, 0.6); }
  .tool-call .args { color: rgba(192, 208, 224, 0.3); }

  /* Data display */
  .data-block {
    background: rgba(0, 212, 255, 0.03);
    border: 1px solid rgba(0, 212, 255, 0.1);
    border-radius: 4px;
    padding: 12px;
    margin: 8px 0;
    font-size: 11px;
    max-height: 200px;
    overflow: auto;
  }

  .research-badge {
    display: inline-block;
    padding: 2px 8px;
    background: rgba(0, 212, 255, 0.1);
    border: 1px solid rgba(0, 212, 255, 0.2);
    border-radius: 2px;
    font-size: 9px;
    color: #00d4ff;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }

  /* Responsive */
  @media (max-width: 768px) {
    .sidebar { display: none; }
    .msg { max-width: 95%; }
  }
</style>
</head>
<body>
<div class="grid-bg"></div>
<div class="hud-ring"></div>
<div class="hud-ring-inner"></div>

<div class="container">

  <!-- HUD Sidebar -->
  <div class="sidebar">
    <div class="jarvis-logo">
      <div class="icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5"/>
          <line x1="12" y1="22" x2="12" y2="15.5"/>
          <polyline points="22 8.5 12 15.5 2 8.5"/>
          <polyline points="12 2 12 8.5 22 15.5"/>
          <polyline points="12 2 12 8.5 2 15.5"/>
        </svg>
      </div>
      <h1>J.A.R.V.I.S.</h1>
      <div class="sub">Omega Protocol</div>
    </div>

    <div class="hud-section">
      <div class="hud-section-title">System Status</div>
      <div class="status-indicator">
        <div class="status-dot" id="statusDot"></div>
        <div class="status-text" id="statusText">ONLINE</div>
      </div>
    </div>

    <div class="hud-section">
      <div class="hud-section-title">Performance</div>
      <div class="stat-row"><span class="label">UPTIME</span><span class="value" id="uptime">0s</span></div>
      <div class="stat-row"><span class="label">AGENT</span><span class="value" id="agentStatus">${this.agentId ? "ACTIVE" : "BOOT"}</span></div>
      <div class="stat-row"><span class="label">CLIENTS</span><span class="value" id="clientCount">0</span></div>
      <div class="stat-row"><span class="label">MEMORY</span><span class="value" id="memoryUsage">-- MB</span></div>
    </div>

    <div class="hud-section">
      <div class="hud-section-title">Quick Access</div>
      <div class="quick-actions">
        <button class="quick-btn" onclick="sendPreset('deep research')">&#x1F50D; Research</button>
        <button class="quick-btn" onclick="sendPreset('run system check')">&#x2699; Diag</button>
        <button class="quick-btn" onclick="sendPreset('what can you do')">&#x2753; Help</button>
        <button class="quick-btn" onclick="sendPreset('current weather and news')">&#x1F4F0; Intel</button>
      </div>
    </div>

    <div style="margin-top: auto; font-size: 9px; color: rgba(0,212,255,0.2); text-align: center; letter-spacing: 2px;">
      v1.0.0 — OMEGA PROTOCOL
    </div>
  </div>

  <!-- Main Chat Panel -->
  <div class="main">
    <div class="top-bar">
      <span class="status-line">STATUS: <span class="highlight" id="statusLine">ALL SYSTEMS NOMINAL</span></span>
      <span class="title">// OMEGA INTERFACE</span>
    </div>

    <div class="chat-area" id="chat">
      <div class="msg system">
        <div class="role-tag">&#x25B6; System</div>
        <div class="text">J.A.R.V.I.S. Omega Protocol initialized. All systems operational. How may I assist you, Sir?</div>
      </div>
    </div>

    <div class="thinking" id="thinking" style="display:none; padding-left: 24px;">
      <span>PROCESSING</span>
      <span class="dots">
        <span></span><span></span><span></span>
      </span>
    </div>

    <div class="input-area">
      <span class="prompt">SIR&gt;</span>
      <input type="text" id="input" placeholder="Enter command or query..." autofocus />
      <button id="sendBtn" onclick="send()">Execute</button>
    </div>
  </div>
</div>

<script>
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host);
  const chat = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('sendBtn');
  const thinking = document.getElementById('thinking');

  let isProcessing = false;

  ws.onopen = () => {
    updateStatus('ONLINE', 'ALL SYSTEMS NOMINAL');
  };

  ws.onclose = () => {
    updateStatus('WARNING', 'CONNECTION LOST', 'warning');
  };

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    isProcessing = false;
    thinking.style.display = 'none';
    sendBtn.disabled = false;
    input.disabled = false;

    if (data.type === 'response') {
      addMsg('assistant', data.payload.response);
    } else if (data.type === 'error') {
      addMsg('system', 'Error: ' + data.payload.message);
    }
  };

  function updateStatus(text, line, type) {
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    const lineEl = document.getElementById('statusLine');
    if (txt) txt.textContent = text;
    if (lineEl) lineEl.textContent = line;
    if (dot) {
      dot.className = 'status-dot' + (type === 'warning' ? ' warning' : type === 'error' ? ' error' : '');
    }
  }

  function addMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;

    const roleNames = { user: 'COMMAND', assistant: 'JARVIS', system: 'SYSTEM' };
    const tag = document.createElement('div');
    tag.className = 'role-tag';
    tag.textContent = '\u25B6 ' + (roleNames[role] || role.toUpperCase());
    div.appendChild(tag);

    const textDiv = document.createElement('div');
    textDiv.className = 'text';

    // Check for structured data in assistant responses
    if (role === 'assistant' && text.includes('"synthesis"')) {
      try {
        const data = JSON.parse(text);
        if (data.data) {
          // Research result display
          const badge = document.createElement('div');
          badge.className = 'research-badge';
          badge.textContent = '\\u2302 RESEARCH COMPLETE';
          div.appendChild(badge);

          if (data.data.synthesis) text = data.data.synthesis;
        }
      } catch {}
    }

    // Format tool calls nicely
    if (role === 'assistant' && text.includes('{"name":"')) {
      textDiv.textContent = text;
    } else {
      textDiv.textContent = text;
    }

    div.appendChild(textDiv);
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }

  function send() {
    const msg = input.value.trim();
    if (!msg || isProcessing) return;
    sendMessage(msg);
  }

  function sendPreset(msg) {
    if (isProcessing) return;
    sendMessage(msg);
  }

  function sendMessage(msg) {
    addMsg('user', msg);
    input.value = '';
    isProcessing = true;
    thinking.style.display = 'flex';
    sendBtn.disabled = true;
    input.disabled = true;
    ws.send(JSON.stringify({ type: 'chat', payload: { message: msg } }));
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') send();
  });

  // Auto-update uptime
  const startTime = Date.now();
  setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    document.getElementById('uptime').textContent = m + 'm ' + s + 's';
    // Update memory roughly
    const mem = (performance.memory?.usedJSHeapSize / 1048576 || Math.random() * 50 + 30).toFixed(0);
    document.getElementById('memoryUsage').textContent = mem + ' MB';
    document.getElementById('clientCount').textContent = '${this.clients.size}';
  }, 1000);

  // Focus input
  input.focus();
</script>
</body>
</html>`;
  }
}
