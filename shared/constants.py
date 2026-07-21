# ====================================================================
# JARVIS OMEGA — System Constants
# ====================================================================
"""
All system-wide constants, enumerations, and category definitions.
Single source of truth for magic strings across the entire system.
"""

from enum import Enum
import re

# ---- System Identity ----
SYSTEM_NAME = "JARVIS OMEGA"
SYSTEM_VERSION = "1.0.0"
USER_TITLE = "Sir"

# ---- Agent Types ----
class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    CODE = "code"
    DOCUMENT = "document"
    VIDEO = "video"
    OS = "os"
    VISION = "vision"
    MONITOR = "monitor"
    DEPLOYMENT = "deployment"
    TESTING = "testing"
    REPAIR = "repair"
    MEMORY = "memory"
    SECURITY = "security"
    BROWSER = "browser"
    RESEARCH = "research"
    PLANNER = "planner"
    WORKER = "worker"
    SELF_MODIFY = "self_modify"  # Phase 9 — self-modification agent

# ---- Agent Status ----
class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"
    RECOVERING = "recovering"
    SPAWNING = "spawning"

# ---- Task Status ----
class TaskStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    AWAITING_APPROVAL = "awaiting_approval"

# ---- Task Priority ----
class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# ---- Risk Level ----
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---- Risk Tier (used by tool registry and command safety validator) ----
class RiskTier(str, Enum):
    """Capability tiers enforced by the approval gateway."""

    TIER_0_OBSERVE = "tier_0_observe"          # read-only: list, read, search
    TIER_1_REVERSIBLE = "tier_1_reversible"    # in-workspace writes, git commit
    TIER_2_SYSTEM = "tier_2_system"            # install, kill proc, open app
    TIER_3_DESTRUCTIVE = "tier_3_destructive"  # delete, format, net ops
    TIER_4_EXTERNAL = "tier_4_external"        # email, post, pay, SMS


# Risk tiers that ALWAYS require explicit Sir approval.
APPROVAL_REQUIRED_TIERS = {
    RiskTier.TIER_2_SYSTEM,
    RiskTier.TIER_3_DESTRUCTIVE,
    RiskTier.TIER_4_EXTERNAL,
}


# ---- Dangerous command patterns (shell-level, used by CommandSafety) ----
# Each entry: (compiled regex, reason). Matched case-insensitively against the
# normalized command string. A match routes the command to the approval gateway
# instead of executing immediately.
DANGEROUS_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+-rf?\s+/(?:\s|$|\b)"), "recursive delete from root"),
    (re.compile(r"\brm\s+-rf?\s+[A-Z]:\\", re.IGNORECASE), "recursive delete from drive root (Windows)"),
    (re.compile(r"\bdel\s+(?:/[fsq]+\s+)+C:\\", re.IGNORECASE), "force-delete from C:\\ (Windows)"),
    (re.compile(r"\brmdir\s+/s\s+/q", re.IGNORECASE), "recursive rmdir (Windows)"),
    (re.compile(r"\berase\s+(?:/[fsq]+\s+)+C:\\", re.IGNORECASE), "force-erase from C:\\ (Windows)"),
    (re.compile(r"\bformat\s+[A-Z]:", re.IGNORECASE), "format drive"),
    (re.compile(r"\bmkfs(\.\w+)?\s+/dev/", re.IGNORECASE), "mkfs on device"),
    (re.compile(r"\bdd\s+if=.*\s+of=/dev/"), "dd write to device"),
    (re.compile(r">\s*/dev/sd[a-z]"), "overwrite raw disk"),
    (re.compile(r"\bshutdown\b", re.IGNORECASE), "system shutdown"),
    (re.compile(r"\breboot\b", re.IGNORECASE), "system reboot"),
    (re.compile(r"\bhalt\b", re.IGNORECASE), "system halt"),
    (re.compile(r"\bpoweroff\b", re.IGNORECASE), "system poweroff"),
    (re.compile(r"\breg\s+delete\b", re.IGNORECASE), "registry deletion (Windows)"),
    (re.compile(r"\bregedit\s+/s", re.IGNORECASE), "silent registry import (Windows)"),
    (re.compile(r"\btakeown\s+/f\s+C:\\", re.IGNORECASE), "take ownership of drive"),
    (re.compile(r"\bicacls\s+C:\\.*[+/][gt]rant", re.IGNORECASE), "ACL grant on root"),
    (re.compile(r"\bnet\s+user\b.*\s/add\b", re.IGNORECASE), "create user account"),
    (re.compile(r"\bnet\s+localgroup\s+administrators\b", re.IGNORECASE), "modify administrators group"),
    (re.compile(r"\bschtasks\s+/create\b", re.IGNORECASE), "create scheduled task"),
    (re.compile(r"\bcurl\s+.*\|\s*(bash|sh|zsh)\b"), "curl-pipe-shell (remote script exec)"),
    (re.compile(r"\bwget\s+.*\|\s*(bash|sh|zsh)\b"), "wget-pipe-shell (remote script exec)"),
    (re.compile(r"\biex\(.*Invoke-WebRequest", re.IGNORECASE), "PowerShell remote exec"),
    (re.compile(r"\bInvoke-Expression.*WebRequest", re.IGNORECASE), "PowerShell remote exec"),
    (re.compile(r"\bcrontab\s+-r\b"), "delete crontab"),
    (re.compile(r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)"), "world-writable root"),
    (re.compile(r":\(\)\s*\{.*\};:"), "fork bomb"),
    (re.compile(r"\btaskkill\s+/[fF].*\s+/[iI][mM]\s+", re.IGNORECASE), "force kill process (Windows)"),
]

# Patterns that are unconditionally blocked (cannot be approved): these touch
# fundamental system integrity in ways that have no legitimate use through JARVIS.
BLOCKED_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+-rf?\s+/\s*$"), "refusing to delete root filesystem"),
    (re.compile(r":\(\)\s*\{.*\};:"), "refusing fork bomb"),
    (re.compile(r"\bmkfs(\.\w+)?\s+/dev/sd[a-z]\b", re.IGNORECASE), "refusing to format boot disk"),
    (re.compile(r"\bdd\s+if=.*\s+of=/dev/sd[a-z]\b"), "refusing dd to whole disk"),
]

# Maximum length of a single command string accepted by the chat router.
MAX_COMMAND_LENGTH = 4096


# --------------------------------------------------------------------
# Phase 9 — Self-Healing & Self-Modification guardrails
# --------------------------------------------------------------------

# Files the self-modification agent is NEVER allowed to edit, even when
# ALLOW_SELF_MODIFICATION=True. These are the load-bearing safety circuit
# breakers; touching them would let JARVIS disable its own oversight.
SELF_MODIFY_PROTECTED_PATHS = [
    "shared/security.py",          # JWT + Fernet bootstrap
    "shared/constants.py",         # this file (would let JARVIS edit its own guardrails)
    "backend/services/command_safety.py",  # the RCE-prevention validator
    "backend/approval_gateway.py", # human-in-the-loop gate
    "backend/config.py",           # validate_security_settings + ALLOW_SELF_MODIFICATION
    "backend/self_heal.py",        # the supervisor itself
    "local_client/agents/agent_self_modify.py",  # the self-edit agent
    ".env",                        # secrets
    "conftest.py",                 # test bootstrap
]

# File globs the self-modification agent MAY edit when ALLOW_SELF_MODIFICATION
# is enabled. Anything not in PROTECTED and matching one of these patterns
# is fair game.
SELF_MODIFY_ALLOWED_GLOBS = [
    "backend/**/*.py",
    "local_client/**/*.py",
    "shared/**/*.py",
    "plugins/**/*.py",
    "backend/tests/**/*.py",
]

# How many failed attempts the never-give-up loop tolerates before backing off.
SELF_MODIFY_MAX_ATTEMPTS = 8

# How many minutes the never-give-up loop runs before timing out.
SELF_MODIFY_TIMEOUT_MINUTES = 30

# Where backup copies of edited files land before a patch is applied.
SELF_MODIFY_BACKUP_DIR = "./storage/self_modify_backups"

# Where patch audit records (one JSON per attempt) land.
SELF_MODIFY_AUDIT_DIR = "./storage/self_modify_audit"

# ---- Health State ----
class HealthState(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    OFFLINE = "offline"


# ---- Device Type ----
class DeviceType(str, Enum):
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    MOBILE = "mobile"
    TABLET = "tablet"
    BROWSER = "browser"
    UNKNOWN = "unknown"

# ---- Memory Categories ----
class MemoryCategory(str, Enum):
    CONVERSATIONS = "memory_conversations"
    PROJECTS = "memory_projects"
    DOCUMENTS = "memory_documents"
    CODE = "memory_code"
    TASKS = "memory_tasks"
    DEVICES = "memory_devices"
    DEPLOYMENTS = "memory_deployments"
    RESEARCH = "memory_research"
    DEBUGGING = "memory_debugging"
    PREFERENCES = "memory_preferences"

# ---- Event Types ----
class EventType(str, Enum):
    AGENT_SPAWNED = "agent_spawned"
    AGENT_TERMINATED = "agent_terminated"
    AGENT_FAILED = "agent_failed"
    AGENT_COMPLETED = "agent_completed"
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    MEMORY_STORED = "memory_stored"
    MEMORY_RETRIEVED = "memory_retrieved"
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    DEVICE_PAIRED = "device_paired"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    SCREENSHOT_CAPTURED = "screenshot_captured"
    VOICE_COMMAND = "voice_command"
    CLIPBOARD_SYNCED = "clipboard_synced"
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"
    HEALTH_WARNING = "health_warning"
    HEALTH_CRITICAL = "health_critical"
    HEALTH_ALERT = "health_alert"
    SECURITY_EVENT = "security_event"
    BACKUP_COMPLETED = "backup_completed"
    FILE_MODIFIED = "file_modified"
    PROJECT_SCANNED = "project_scanned"
    SYSTEM_ERROR = "system_error"

# ---- Audit Log Categories ----
class AuditCategory(str, Enum):
    AUTHENTICATION = "authentication"
    MEMORY = "memory"
    PROJECTS = "projects"
    AGENTS = "agents"
    DEPLOYMENTS = "deployments"
    APPROVALS = "approvals"
    SECURITY = "security"
    DEVICES = "devices"
    FILES = "files"
    SYSTEM = "system"

# ---- WebSocket Message Types ----
class WSMessageType(str, Enum):
    CHAT = "chat"
    CHAT_RESPONSE = "chat_response"
    CHAT_STREAM = "chat_stream"
    AGENT_UPDATE = "agent_update"
    TASK_UPDATE = "task_update"
    HEALTH_UPDATE = "health_update"
    DEVICE_UPDATE = "device_update"
    MEMORY_UPDATE = "memory_update"
    CLIPBOARD_SYNC = "clipboard_sync"
    SCREENSHOT = "screenshot"
    VOICE_DATA = "voice_data"
    VOICE_RESPONSE = "voice_response"
    NOTIFICATION = "notification"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    TERMINAL_LOG = "terminal_log"
    HEARTBEAT = "heartbeat"
    SYSTEM_VITALS = "system_vitals"
    PROJECT_UPDATE = "project_update"
    DEPLOYMENT_UPDATE = "deployment_update"
    EXECUTE_TASK = "execute_task"
    TASK_RESULT = "task_result"
    ERROR = "error"

# ---- Recovery Stages ----
class RecoveryStage(str, Enum):
    RETRY = "retry"
    RESTART_AGENT = "restart_agent"
    SPAWN_REPLACEMENT = "spawn_replacement"
    REBUILD_CONTEXT = "rebuild_context"
    ESCALATE = "escalate_to_supervisor"

# ---- Model Identifiers ----
MODELS = {
    "reasoning": "gryphe/mythomax-l2-13b",
    "vision": "qwen/qwen2.5-vl-72b-instruct",
    "stt": "whisper-large-v3-turbo",
    "tts": "kokoro-82m",
}

# ---- Dangerous Actions (require approval) ----
DANGEROUS_ACTIONS = [
    "delete_project",
    "delete_database",
    "delete_repository",
    "reset_workspace",
    "mass_file_deletion",
    "credential_removal",
    "production_rollback",
    "os_modification",
    "format_drive",
    "account_deletion",
    "database_destruction",
]

# ---- Safe Actions (no approval needed) ----
SAFE_ACTIONS = [
    "write_code",
    "modify_file",
    "install_dependency",
    "create_folder",
    "fix_bug",
    "run_test",
    "generate_document",
    "create_diagram",
    "launch_dev_server",
    "read_file",
    "scan_project",
    "search_memory",
]
