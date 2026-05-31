# ====================================================================
# JARVIS OMEGA — Models Unit Tests
# ====================================================================
"""
Unit tests for shared Pydantic models.
"""

from datetime import datetime
from shared.models import (
    AgentMessage,
    TaskDefinition,
    DeviceInfo,
    MemoryEntry,
    WSMessage,
    AuditLogEntry,
)
from shared.constants import (
    TaskPriority,
    TaskStatus,
    AgentType,
    DeviceType,
    MemoryCategory,
    WSMessageType,
    AuditCategory,
)


def test_agent_message_model():
    """Test validation and default values of AgentMessage model."""
    msg = AgentMessage(
        sender="orchestrator",
        receiver="code_agent",
        intent="refactor_code",
        payload={"file": "main.py"},
    )
    assert msg.sender == "orchestrator"
    assert msg.receiver == "code_agent"
    assert msg.intent == "refactor_code"
    assert msg.payload == {"file": "main.py"}
    assert msg.priority == TaskPriority.MEDIUM
    assert msg.status == TaskStatus.QUEUED
    assert isinstance(msg.timestamp, datetime)
    assert isinstance(msg.task_id, str) and len(msg.task_id) > 0


def test_task_definition_model():
    """Test validation and defaults of TaskDefinition."""
    task = TaskDefinition(
        title="Check system logs",
        description="Search for database connection warnings.",
        agent_type=AgentType.MONITOR,
    )
    assert task.title == "Check system logs"
    assert task.agent_type == AgentType.MONITOR
    assert task.priority == TaskPriority.MEDIUM
    assert task.status == TaskStatus.QUEUED
    assert task.timeout == 300
    assert task.max_retries == 3


def test_device_info_model():
    """Test validation and defaults of DeviceInfo."""
    device = DeviceInfo(
        device_name="Workstation-A",
        device_type=DeviceType.DESKTOP,
        platform="Windows",
        ip_address="192.168.1.5",
    )
    assert device.device_name == "Workstation-A"
    assert device.device_type == DeviceType.DESKTOP
    assert device.platform == "Windows"
    assert device.trusted is False
    assert device.online is False


def test_memory_entry_model():
    """Test validation and defaults of MemoryEntry."""
    mem = MemoryEntry(
        category=MemoryCategory.PREFERENCES,
        content="Sir prefers dark mode dashboards.",
        source="dashboard_frontend",
    )
    assert mem.category == MemoryCategory.PREFERENCES
    assert mem.content == "Sir prefers dark mode dashboards."
    assert mem.source == "dashboard_frontend"
    assert mem.pinned is False



def test_ws_message_model():
    """Test validation and serialization of WSMessage."""
    msg = WSMessage(
        type=WSMessageType.HEARTBEAT,
        payload={"latency_ms": 12.5},
    )
    assert msg.type == WSMessageType.HEARTBEAT
    assert msg.payload == {"latency_ms": 12.5}
    assert isinstance(msg.request_id, str)
    
    # Check serialization
    data = msg.model_dump()
    assert data["type"] == WSMessageType.HEARTBEAT.value
    assert data["payload"] == {"latency_ms": 12.5}
