# ====================================================================
# JARVIS OMEGA — Agent Subsystem Package
# ====================================================================
"""
Package definition for JARVIS OMEGA local client agents.
Enables clean runtime dynamic importing of specialized agents.
"""

from local_client.agents.agent_orchestrator import orchestrator
from local_client.agents.agent_code import AgentCode
from local_client.agents.agent_document import AgentDocument
from local_client.agents.agent_video import AgentVideo
from local_client.agents.agent_os import AgentOs
from local_client.agents.agent_vision import AgentVision
from local_client.agents.agent_monitor import AgentMonitor
from local_client.agents.agent_deployment import AgentDeployment
from local_client.agents.agent_testing import AgentTesting
from local_client.agents.agent_repair import AgentRepair
from local_client.agents.agent_memory import AgentMemory
from local_client.agents.agent_security import AgentSecurity
from local_client.agents.agent_browser import AgentBrowser
from local_client.agents.agent_research import AgentResearch
from local_client.agents.agent_planner import AgentPlanner

__all__ = [
    "orchestrator",
    "AgentCode",
    "AgentDocument",
    "AgentVideo",
    "AgentOs",
    "AgentVision",
    "AgentMonitor",
    "AgentDeployment",
    "AgentTesting",
    "AgentRepair",
    "AgentMemory",
    "AgentSecurity",
    "AgentBrowser",
    "AgentResearch",
    "AgentPlanner",
]
