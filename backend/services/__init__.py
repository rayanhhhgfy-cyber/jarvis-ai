# ====================================================================
# JARVIS OMEGA — Backend Services Package
# ====================================================================

from backend.services.notification_service import notification_service
from backend.services.approval_service import approval_service
from backend.services.memory_service import memory_service
from backend.services.transcription_service import transcription_service
from backend.services.tts_service import tts_service
from backend.services.vision_service import vision_service
from backend.services.llm_service import llm_service

# Phase 3 Services
from backend.services.sound_engine import sound_engine
from backend.services.recovery_engine import auto_debug, supply_chain_watchdog
from backend.services.web_search_service import web_search_service
from backend.services.excel_service import excel_service
from backend.services.file_download_service import file_download_service
from backend.services.goal_executor import goal_executor
from backend.services.pattern_detector import pattern_detector
from backend.services.mcp_service import mcp_service
from backend.services.skill_manager import skill_manager


# Phase 4 Services
from backend.services.system_pulse import system_monitor, gaming_detector, predictive_prefetcher, voice_broadcast
from backend.services.lazarus_sentry import lazarus_sentry
from backend.services.crypt_vault import crypt_vault
from backend.services.pentest_sentry import pentest_sentry
from backend.services.network_sentry import network_sentry
from backend.services.guardrail_shield import guardrail_shield
from backend.services.phantom_browser import phantom_browser
from backend.services.mcp_client import mcp_client
from backend.services.db_heartbeat import db_heartbeat
from backend.services.ui_sentry import ui_sentry
from backend.services.data_inspector import data_inspector
from backend.services.code_war_engine import code_war_engine
from backend.services.skill_harvester import skill_harvester
from backend.services.knowledge_ingestor import knowledge_ingestor
from backend.services.presentation_forge import presentation_forge
from backend.services.traffic_simulator import traffic_simulator
from backend.services.game_memory_modder import game_memory_modder

__all__ = [
    "notification_service", "approval_service", "memory_service",
    "transcription_service", "tts_service", "vision_service", "llm_service",
    "sound_engine", "auto_debug", "supply_chain_watchdog", "web_search_service", "excel_service",
    "file_download_service", "goal_executor", "pattern_detector", "mcp_service",
    "skill_manager",
    "system_monitor", "gaming_detector", "predictive_prefetcher", "voice_broadcast",
    "lazarus_sentry", "crypt_vault", "pentest_sentry", "network_sentry",
    "guardrail_shield", "phantom_browser", "mcp_client", "db_heartbeat",
    "ui_sentry", "data_inspector", "code_war_engine", "skill_harvester",
    "knowledge_ingestor", "presentation_forge", "traffic_simulator",
    "game_memory_modder",
]
