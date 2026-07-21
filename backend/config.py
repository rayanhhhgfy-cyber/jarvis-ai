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

from pydantic import field_validator
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
    # No default — startup will fail fast if unset so tokens stay stable across
    # restarts. Generate with:  python -c "import secrets; print(secrets.token_urlsafe(64))"
    backend_secret_key: str = ""
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

    # ---- LLM ----
    llm_max_tokens: int = 1500

    # ---- Voice / Audio ----
    microphone_vad_threshold: float = 0.03
    clipboard_poll_interval: float = 1.0

    # ---- Dialogue History ----
    dialogue_history_max_turns: int = 20

    # ---- Phase 9: Self-Healing & Self-Modification ----
    # When True, JARVIS may autonomously edit its own source code (within the
    # protected-paths guardrails in shared/constants.py) when a task fails.
    # Backups of every edited file are written to SELF_MODIFY_BACKUP_DIR.
    # When False, self-modification still fires but routes through the normal
    # approval gateway (Tier 3 destructive).
    allow_self_modification: bool = False
    # When True, the supervisor subscribes to unhandled exceptions and tries
    # to diagnose + patch them without Sir's intervention.
    auto_self_heal: bool = True
    # How many repair iterations the never-give-up loop attempts.
    self_modify_max_attempts: int = 8
    # How many minutes the never-give-up loop runs before timing out.
    self_modify_timeout_minutes: int = 30

    # ---- Phase 11: Autonomous Marketing Agency ----
    # When True, JARVIS can post to social media, deploy websites, send
    # outreach emails, and process payments WITHOUT per-action approval
    # (still respects per-tool approval in vault). When False, every
    # external action routes through the approval gateway.
    allow_autonomous_business: bool = False
    # How often (hours) the opportunity scanner runs in the background.
    opportunity_scan_interval_hours: int = 6
    # Default niche used when Sir hasn't picked one. Empty = no default.
    default_niche: str = ""
    # Currency code used by payments / ecommerce tools.
    business_currency: str = "USD"

    # ---- Phase 12: Localization + Scale ----
    # Default locale settings - JARVIS auto-localizes per Sir's location.
    # Sir is based in Amman, Jordan → Arabic-first, JD currency, RTL layout.
    default_language: str = "ar"           # ar | en | mixed
    default_country: str = "JO"            # ISO-3166-1 alpha-2
    default_country_name: str = "Jordan"
    default_city: str = "Amman"
    default_currency: str = "JOD"          # ISO-4217
    default_currency_symbol: str = "د.أ"   # Jordanian Dinar Arabic symbol
    default_currency_exchange_rate: float = 0.71  # 1 USD ≈ 0.71 JOD
    default_timezone: str = "Asia/Amman"
    rtl_layout: bool = True                # Arabic/Hebrew etc → right-to-left
    # Max businesses in the portfolio.
    portfolio_max_businesses: int = 50
    # How many products to build per niche (multi-product mode).
    products_per_niche: int = 7
    # Lead-gen default limit per call.
    leads_per_call: int = 50
    # Continuous mode — build a new business every N hours forever.
    continuous_build_interval_hours: int = 24
    # Always-on never-stop mode.
    never_stop: bool = True

    # ---- Phase 14: Empire gates ----
    # Real-money gates (all default False — must explicitly enable).
    allow_ad_spend: bool = False
    ad_spend_daily_cap_usd: float = 50.0
    execute_real_trade: bool = False
    allow_real_payouts: bool = False

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

    # ------------------------------------------------------------------
    # Validators — empty strings from .env shouldn't break integer fields
    # ------------------------------------------------------------------

    @field_validator("chroma_port", "backend_port", "ws_heartbeat_interval",
                     "ws_reconnect_delay", "ws_max_reconnect_attempts",
                     "access_token_expire_minutes", "refresh_token_expire_days",
                     "device_token_expire_days", "max_concurrent_agents",
                     "agent_timeout_seconds", "max_retry_count",
                     "dialogue_history_max_turns", mode="before")
    @classmethod
    def _empty_str_to_zero(cls, v):
        """Tolerate ``KEY=`` (empty string) in .env for integer settings."""
        if v is None or v == "":
            return 0
        return v

    @field_validator("allow_self_modification", "auto_self_heal",
                     "allow_autonomous_business", mode="before")
    @classmethod
    def _empty_str_to_false(cls, v):
        """Tolerate ``KEY=`` (empty) in .env for boolean settings."""
        if v is None or v == "":
            return False
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    @field_validator("max_cpu_percent", "max_memory_percent",
                     "llm_max_tokens", "microphone_vad_threshold",
                     "clipboard_poll_interval", mode="before")
    @classmethod
    def _empty_str_to_float_zero(cls, v):
        if v is None or v == "":
            return 0.0
        return v

    def validate_security_settings(self) -> None:
        """
        Fail fast if bootstrap secrets are missing or set to known placeholders.

        Without ``backend_secret_key``, JWT signatures change on every restart
        and trusted devices are untrusted (the WebSocket 403 storm). Without
        ``encryption_key``, Fernet-encrypted data in the DB becomes unreadable
        across restarts because ``shared.security`` would otherwise silently
        generate a new random key each boot.
        """
        placeholders = {
            "",
            "change_this_to_a_strong_random_secret_key",
            "jarvis-omega-change-this-secret",
            "jarvis-omega-default-secret-change-me",
            "REPLACE_ME",
        }
        if self.backend_secret_key in placeholders:
            raise RuntimeError(
                "BACKEND_SECRET_KEY is missing or set to a placeholder. "
                "Generate one with:  python -c \"import secrets; "
                "print(secrets.token_urlsafe(64))\"  and put it in your .env"
            )
        if self.encryption_key in placeholders:
            raise RuntimeError(
                "ENCRYPTION_KEY is missing. Generate one with:  python -c "
                "\"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"  and put it in your .env"
            )


# Singleton settings instance
settings = Settings()
