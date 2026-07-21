# ====================================================================
# JARVIS OMEGA — Shared Pydantic Models
# ====================================================================
"""
All data models used across backend, local client, and agents.
These models define the structured communication protocol.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from shared.constants import (
    AgentStatus,
    AgentType,
    AuditCategory,
    DeviceType,
    EventType,
    HealthState,
    MemoryCategory,
    RiskLevel,
    TaskPriority,
    TaskStatus,
    WSMessageType,
)


def gen_id() -> str:
    return str(uuid.uuid4())


def now_ts() -> datetime:
    return datetime.utcnow()


# ====================================================================
# AGENT MODELS
# ====================================================================

class AgentMessage(BaseModel):
    """Structured JSON communication between agents."""
    sender: str
    receiver: str
    task_id: str = Field(default_factory=gen_id)
    intent: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.QUEUED
    timestamp: datetime = Field(default_factory=now_ts)


class AgentInfo(BaseModel):
    """Runtime information about a spawned agent."""
    agent_id: str = Field(default_factory=gen_id)
    agent_type: AgentType
    task_id: Optional[str] = None
    parent_id: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    task_count: int = 0
    created_at: datetime = Field(default_factory=now_ts)
    updated_at: datetime = Field(default_factory=now_ts)
    execution_history: List[str] = Field(default_factory=list)
    current_task_description: Optional[str] = None
    error: Optional[str] = None
    children: List[str] = Field(default_factory=list)


# ====================================================================
# TASK MODELS
# ====================================================================

class TaskDefinition(BaseModel):
    """A task to be executed by an agent."""
    task_id: str = Field(default_factory=gen_id)
    title: str
    description: str
    agent_type: AgentType
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.QUEUED
    assigned_agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    subtasks: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cpu_budget: float = 50.0
    memory_budget: float = 512.0  # MB
    timeout: int = 300  # seconds
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=now_ts)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    device_id: Optional[str] = None


class TaskResult(BaseModel):
    """Result returned by an agent after task execution."""
    task_id: str
    agent_id: str
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    artifacts: List[str] = Field(default_factory=list)
    memory_entries: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=now_ts)


# ====================================================================
# DEVICE MODELS
# ====================================================================

class DeviceInfo(BaseModel):
    """Information about a connected device."""
    device_id: str = Field(default_factory=gen_id)
    device_name: str
    device_type: DeviceType = DeviceType.UNKNOWN
    device_secret: Optional[str] = None
    platform: str = ""
    ip_address: str = ""
    latency_ms: float = 0.0
    battery_level: Optional[float] = None
    is_charging: Optional[bool] = None
    trusted: bool = False
    online: bool = False
    last_seen: datetime = Field(default_factory=now_ts)
    registered_at: datetime = Field(default_factory=now_ts)
    capabilities: List[str] = Field(default_factory=list)
    running_agents: List[str] = Field(default_factory=list)
    current_tasks: List[str] = Field(default_factory=list)


class DevicePairingRequest(BaseModel):
    """Request to pair a new device."""
    device_name: str
    device_type: DeviceType
    platform: str
    pairing_code: Optional[str] = None


class DevicePairingResponse(BaseModel):
    """Response after device pairing approval."""
    device_id: str
    device_secret: str
    access_token: str
    refresh_token: str
    pairing_code: str
    approved: bool = False


# ====================================================================
# MEMORY MODELS
# ====================================================================

class MemoryEntry(BaseModel):
    """A single memory entry stored in ChromaDB."""
    memory_id: str = Field(default_factory=gen_id)
    category: MemoryCategory
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    tags: List[str] = Field(default_factory=list)
    pinned: bool = False
    created_at: datetime = Field(default_factory=now_ts)
    updated_at: datetime = Field(default_factory=now_ts)
    relevance_score: float = 0.0


class MemoryQuery(BaseModel):
    """Query for semantic memory search."""
    query: str
    categories: List[MemoryCategory] = Field(default_factory=list)
    top_k: int = 10
    min_relevance: float = 0.0
    tags: List[str] = Field(default_factory=list)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class MemoryContext(BaseModel):
    """Aggregated memory context for LLM reasoning."""
    general_memories: List[MemoryEntry] = Field(default_factory=list)
    project_memories: List[MemoryEntry] = Field(default_factory=list)
    task_memories: List[MemoryEntry] = Field(default_factory=list)
    debugging_memories: List[MemoryEntry] = Field(default_factory=list)
    preference_memories: List[MemoryEntry] = Field(default_factory=list)


# ====================================================================
# APPROVAL MODELS
# ====================================================================

class ApprovalRequest(BaseModel):
    """Request for human approval on a dangerous action."""
    approval_id: str = Field(default_factory=gen_id)
    action: str
    reason: str
    risk_level: RiskLevel
    affected_resources: List[str] = Field(default_factory=list)
    expected_result: str = ""
    undo_possible: bool = False
    requesting_agent: str = ""
    task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=now_ts)
    approved: Optional[bool] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


# ====================================================================
# WEBSOCKET MODELS
# ====================================================================

class WSMessage(BaseModel):
    """WebSocket message envelope."""
    type: WSMessageType
    device_id: str = ""
    session_token: str = ""
    timestamp: datetime = Field(default_factory=now_ts)
    payload: Dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default_factory=gen_id)


# ====================================================================
# HEALTH MODELS
# ====================================================================

class SystemVitals(BaseModel):
    """System resource metrics."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    network_sent_mb: float = 0.0
    network_recv_mb: float = 0.0
    gpu_percent: Optional[float] = None
    gpu_memory_percent: Optional[float] = None
    cpu_temperature: Optional[float] = None
    active_agents: int = 0
    queued_tasks: int = 0
    health_state: HealthState = HealthState.HEALTHY
    timestamp: datetime = Field(default_factory=now_ts)


class ComponentHealth(BaseModel):
    """Health status of a single system component."""
    name: str
    state: HealthState = HealthState.HEALTHY
    message: str = ""
    latency_ms: float = 0.0
    last_check: datetime = Field(default_factory=now_ts)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HealthSnapshot(BaseModel):
    """
    Unified health snapshot returned by ``GET /health``.

    Replaces the loose ``Dict[str, Any]`` previously returned so the API
    contract is stable, typed, and visible in OpenAPI docs.
    """
    status: str = "online"
    health: HealthState = HealthState.HEALTHY
    scheduler_active: bool = False
    active_connections: int = 0
    tasks_in_queue: int = 0
    timestamp: datetime = Field(default_factory=now_ts)


class VitalsSnapshot(BaseModel):
    """
    Lightweight vitals summary (subset of ``SystemVitals``) used by health
    endpoints that only need a quick glance.
    """
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    health_state: HealthState = HealthState.HEALTHY
    timestamp: datetime = Field(default_factory=now_ts)


# ====================================================================
# PROJECT MODELS
# ====================================================================

class ProjectNode(BaseModel):
    """A node in the project knowledge graph."""
    node_id: str = Field(default_factory=gen_id)
    node_type: str  # file, folder, class, function, service, api, database, dependency
    name: str
    path: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    relationships: List[Dict[str, str]] = Field(default_factory=list)


class ProjectInfo(BaseModel):
    """Summary information about a scanned project."""
    project_id: str = Field(default_factory=gen_id)
    name: str
    path: str
    language: str = ""
    framework: str = ""
    dependencies: List[str] = Field(default_factory=list)
    files_count: int = 0
    total_lines: int = 0
    last_scanned: datetime = Field(default_factory=now_ts)
    architecture_summary: str = ""
    risk_report: str = ""
    tech_debt: List[str] = Field(default_factory=list)
    graph_nodes: List[ProjectNode] = Field(default_factory=list)


# ====================================================================
# NOTIFICATION MODELS
# ====================================================================

class Notification(BaseModel):
    """Push notification payload."""
    notification_id: str = Field(default_factory=gen_id)
    title: str
    body: str
    icon: str = "jarvis"
    category: str = "general"
    priority: TaskPriority = TaskPriority.MEDIUM
    target_devices: List[str] = Field(default_factory=list)
    action_url: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_ts)
    read: bool = False


# ====================================================================
# AUDIT LOG MODEL
# ====================================================================

class AuditLogEntry(BaseModel):
    """Immutable audit log entry."""
    log_id: str = Field(default_factory=gen_id)
    category: AuditCategory
    action: str
    status: str = "success"
    device_id: str = ""
    user: str = "Sir"
    agent: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
    execution_duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=now_ts)


# ====================================================================
# CHAT MODELS
# ====================================================================

class ChatMessage(BaseModel):
    """A single chat message."""
    message_id: str = Field(default_factory=gen_id)
    role: str = "user"  # user | assistant | system
    content: str
    device_id: str = ""
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=now_ts)


class ChatRequest(BaseModel):
    """Request to the chat system."""
    message: str
    conversation_id: Optional[str] = None
    device_id: str = ""
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    include_memory: bool = True
    stream: bool = True


class ChatResponse(BaseModel):
    """Response from the chat system."""
    message_id: str = Field(default_factory=gen_id)
    conversation_id: str = ""
    content: str
    agents_invoked: List[str] = Field(default_factory=list)
    tasks_created: List[str] = Field(default_factory=list)
    memories_stored: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=now_ts)


# ====================================================================
# CLIPBOARD MODELS
# ====================================================================

class ClipboardEntry(BaseModel):
    """A clipboard entry for cross-device sync."""
    entry_id: str = Field(default_factory=gen_id)
    content: str
    content_type: str = "text"
    source_device: str = ""
    encrypted: bool = False
    pinned: bool = False
    category: str = ""
    created_at: datetime = Field(default_factory=now_ts)


# ====================================================================
# BACKUP MODELS
# ====================================================================

class BackupInfo(BaseModel):
    """Information about a backup."""
    backup_id: str = Field(default_factory=gen_id)
    backup_type: str  # memory, projects, configs, logs, workspace
    path: str
    size_bytes: int = 0
    compressed: bool = True
    checksum: str = ""
    created_at: datetime = Field(default_factory=now_ts)
    version: int = 1
