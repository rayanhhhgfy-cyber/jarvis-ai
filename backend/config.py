# ====================================================================
# JARVIS OMEGA — Backend Configuration
# ====================================================================
"""
Pydantic Settings for environment-based configuration.
All settings loaded from .env file or environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment."""

    # ---- API Keys ----
    openrouter_api_key: str = ""
    groq_api_key: str = ""

    # ---- Model Config ----
    mythomax_model: str = "meta-llama/llama-3-8b-instruct"
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

    # ---- VAPID Push ----
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claims_email: str = "sir@jarvis-omega.local"

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
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for attr in [
            "storage_dir", "logs_dir", "workspace_dir",
            "memory_dir", "cache_dir", "backups_dir",
            "chroma_persist_dir",
        ]:
            Path(getattr(self, attr)).mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
