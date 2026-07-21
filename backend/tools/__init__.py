# ====================================================================
# JARVIS OMEGA — Tools package
# ====================================================================
"""
Tool-Use substrate (Phase 8).

Importing ``backend.tools`` gives you the global registry and decorator::

    from backend.tools import tool, get_registry, RiskTier

    @tool(name="my.tool", description="...", risk_tier=RiskTier.TIER_0_OBSERVE)
    async def my_tool(...) -> ...: ...

Plugins under ``plugins/`` auto-register at import time.
"""

from __future__ import annotations

from shared.constants import RiskTier  # re-export
from backend.tools.registry import (
    Tool,
    ToolRegistry,
    tool,
    get_registry,
)

__all__ = [
    "RiskTier",
    "Tool",
    "ToolRegistry",
    "tool",
    "get_registry",
]
