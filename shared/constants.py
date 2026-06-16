# ====================================================================
# JARVIS OMEGA — System Constants
# ====================================================================
"""
All system-wide constants, enumerations, and category definitions.
Single source of truth for magic strings across the entire system.
"""

from enum import Enum

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
    FINANCE = "finance"
    HEALTH = "health"
    SMARTHOME = "smarthome"
    SOCIAL = "social"
    TRAVEL = "travel"
    ENTERTAINMENT = "entertainment"
    LEGAL = "legal"
    SHOPPING = "shopping"
    KNOWLEDGE = "knowledge"
    CREATIVE = "creative"
    CYBERSECURITY = "cybersecurity"
    EDUCATION = "education"
    LOGISTICS = "logistics"
    ANDROID = "android"
    MEETING = "meeting"
    MARKETING = "marketing"
    STARTUP = "startup"

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
