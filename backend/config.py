# ====================================================================
# JARVIS OMEGA — Backend Configuration
# ====================================================================
"""
Pydantic Settings for environment-based configuration.
All settings loaded from .env file or environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings
from shared.logger import get_logger

log = get_logger("config")


class Settings(BaseSettings):
    """Central configuration loaded from environment."""

    # ---- API Keys ----
    openrouter_api_key: str = ""
    openrouter_api_keys: str = ""  # comma-separated fallback keys
    groq_api_key: str = ""
    replicate_api_key: str = ""

    # ---- Model Config ----
    mythomax_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    qwen_vision_model: str = "qwen/qwen2.5-vl-72b-instruct"
    whisper_model: str = "whisper-large-v3-turbo"
    kokoro_model_path: str = "./models/kokoro-82m"

    # ---- Server ----
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_secret_key: str = "jarvis-omega-change-this-secret"
    backend_cors_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # ---- WebSocket ----
    ws_heartbeat_interval: int = 30
    ws_reconnect_delay: int = 5
    ws_max_reconnect_attempts: int = 0  # 0 = unlimited

    # ---- ChromaDB ----
    chroma_persist_dir: str = "./storage/chromadb"
    chroma_host: str = ""
    chroma_port: int = 0

    # ---- SQLite ----
    sqlite_db_path: str = "./storage/jarvis_omega.db"

    # ---- Security ----
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    device_token_expire_days: int = 365
    encryption_key: str = ""

    # ---- Clerk Authentication (JWT via JWKS) ----
    # Configure these for Clerk JWT verification on the backend.
    # Example values:
    # - CLERK_ISSUER: https://<your-clerk-domain>/v1
    # - CLERK_JWKS_URL: https://<your-clerk-domain>/v1/jwks
    # - CLERK_AUDIENCE: your_backend_api_identifier (often your publishable key or custom audience)
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_audience: str = ""
    clerk_clock_skew_seconds: int = 60
    clerk_jwt_algorithms: List[str] = ["RS256"]

    # ---- VAPID Push ----
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claims_email: str = "sir@jarvis-omega.local"

    # ---- Network ----
    lan_ip: str = ""

    # ---- Paths ----
    storage_dir: str = "./storage"
    logs_dir: str = "./logs"
    workspace_dir: str = "./workspace"
    memory_dir: str = "./memory"
    cache_dir: str = "./cache"
    backups_dir: str = "./backups"

    # ---- Resource Limits ----
    max_concurrent_agents: int = 15
    max_cpu_percent: float = 80.0
    max_memory_percent: float = 85.0
    agent_timeout_seconds: int = 300
    max_retry_count: int = 3

    # ---- Wake Word ----
    wake_word: str = "jarvis"
    picovoice_access_key: str = ""

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: str = "json"

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    def get_openrouter_keys(self) -> List[str]:
        """Return all OpenRouter API keys (primary + comma-separated + numbered env vars)."""
        keys = []
        if self.openrouter_api_key:
            keys.append(self.openrouter_api_key)
        for k in self.openrouter_api_keys.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
        # Also scan for OPENROUTER_API_KEY_01 .. _NN pattern
        import os
        for i in range(1, 50):
            val = os.environ.get(f"OPENROUTER_API_KEY_{i:02d}", "") or os.environ.get(f"OPENROUTER_API_KEY_{i}", "")
            if val and val.strip() and val.strip() not in keys:
                keys.append(val.strip())
        return keys

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for attr in [
            "storage_dir", "logs_dir", "workspace_dir",
            "memory_dir", "cache_dir", "backups_dir",
            "chroma_persist_dir",
        ]:
            Path(getattr(self, attr)).mkdir(parents=True, exist_ok=True)
        Path(self.sqlite_db_path).parent.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()


def _detect_lan_ip() -> str:
    """Detect the machine's LAN IP address (non-loopback IPv4)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        # Doesn't actually connect — just used to determine the preferred interface
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return ""


# Auto-detect LAN IP if not explicitly configured
if not settings.lan_ip:
    detected = _detect_lan_ip()
    if detected:
        settings.lan_ip = detected
        log.info("lan_ip_detected", ip=detected)
    else:
        settings.lan_ip = "localhost"
