# ====================================================================
# JARVIS OMEGA — Tool Registry
# ====================================================================
"""
Phase 8 "do anything" substrate.

The ToolRegistry is the single source of truth for every capability JARVIS
can invoke. Each tool is an async (or sync) Python function decorated with
``@tool``. The decorator captures:

  * ``name`` — dotted tool identifier (e.g. ``files.read``)
  * ``description`` — what the tool does, shown to the LLM
  * ``parameters`` — JSON Schema dict describing the arguments
  * ``risk_tier`` — capability tier (0-4) enforced by the approval gateway
  * ``category`` — free-form label (e.g. ``filesystem``, ``shell``, ``messaging``)

The registry exposes:

  * ``register(tool)``              — add a tool
  * ``get(name)``                   — fetch a tool by name
  * ``all_tools()``                 — list everything
  * ``schemas_for_llm()``           — OpenAI/OpenRouter function-calling format
  * ``from_plugin_module(modpath)`` — bulk register everything in a plugin
"""

from __future__ import annotations

import inspect
import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable

from shared.constants import RiskTier
from shared.logger import get_logger

log = get_logger("tool_registry")


# --------------------------------------------------------------------
# Tool dataclass
# --------------------------------------------------------------------

@dataclass
class Tool:
    """A single capability JARVIS can invoke."""

    name: str
    description: str
    func: Callable[..., Awaitable[Any]]
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.TIER_1_REVERSIBLE
    category: str = "general"
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError(
                f"tool name must be dotted (e.g. 'files.read'); got {self.name!r}"
            )
        if not inspect.iscoroutinefunction(self.func):
            raise TypeError(
                f"tool {self.name} function must be async (defined with `async def`)"
            )

    # Make Tool instances directly callable — ``await my_tool(...)`` invokes
    # the wrapped function. Useful in tests and in code that holds a Tool
    # reference and wants to bypass the executor/approval-gateway path.
    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    @property
    def requires_approval(self) -> bool:
        """True if the approval gateway must be consulted before running."""
        from shared.constants import APPROVAL_REQUIRED_TIERS
        return self.risk_tier in APPROVAL_REQUIRED_TIERS

    def to_openai_schema(self) -> Dict[str, Any]:
        """Render the tool in OpenAI/OpenRouter function-calling JSON schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


# --------------------------------------------------------------------
# Decorator
# --------------------------------------------------------------------

def tool(
    name: str,
    description: str,
    parameters: Optional[Dict[str, Any]] = None,
    risk_tier: RiskTier = RiskTier.TIER_1_REVERSIBLE,
    category: str = "general",
    registry: Optional["ToolRegistry"] = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Tool]:
    """
    Decorator that turns an async function into a registered :class:`Tool`.

    Usage::

        @tool(
            name="files.read",
            description="Read a UTF-8 text file from the workspace.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            risk_tier=RiskTier.TIER_0_OBSERVE,
            category="filesystem",
        )
        async def read_file(path: str) -> str:
            return Path(path).read_text(encoding="utf-8")
    """
    def _decorator(func: Callable[..., Awaitable[Any]]) -> Tool:
        t = Tool(
            name=name,
            description=description,
            func=func,
            parameters=parameters or {"type": "object", "properties": {}},
            risk_tier=risk_tier,
            category=category,
        )
        # Register with the provided registry (or the default global one).
        target = registry or _default_registry
        target.register(t)
        # Also return the Tool so plugin authors can keep a reference.
        return t  # type: ignore[return-value]

    return _decorator


# --------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------

class ToolRegistry:
    """Process-wide map of tool name -> Tool."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    # -- core ops ---------------------------------------------------

    def register(self, t: Tool) -> None:
        if t.name in self._tools:
            log.warning("tool_overwriting_existing", name=t.name)
        self._tools[t.name] = t
        log.info("tool_registered", name=t.name, tier=t.risk_tier.value, category=t.category)

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all_tools(self) -> List[Tool]:
        return [t for t in self._tools.values() if t.enabled]

    def tools_by_category(self, category: str) -> List[Tool]:
        return [t for t in self._tools.values() if t.category == category and t.enabled]

    # -- LLM helpers ------------------------------------------------

    def schemas_for_llm(self) -> List[Dict[str, Any]]:
        """All enabled tools, formatted for OpenRouter/OpenAI function calling."""
        return [t.to_openai_schema() for t in self.all_tools()]

    def tool_descriptions(self) -> str:
        """Compact text listing suitable for inclusion in a system prompt."""
        lines: List[str] = []
        for t in self.all_tools():
            lines.append(f"- {t.name}  [{t.risk_tier.value}]  {t.description}")
        return "\n".join(sorted(lines))

    # -- plugin loading --------------------------------------------

    def load_plugin(self, module_path: str) -> int:
        """
        Import a Python module; any ``@tool`` decorator used at import time
        with the default registry will register itself here.

        Returns the number of NEW tools registered from this module.
        """
        global _default_registry
        before = set(self._tools.keys())
        try:
            # Temporarily make ``self`` the default registry so any @tool
            # decorator without an explicit ``registry=`` argument lands here.
            previous = _default_registry
            _default_registry = self
            importlib.import_module(module_path)
            _default_registry = previous
        except Exception as e:
            _default_registry = previous if 'previous' in locals() else _default_registry
            log.error("plugin_load_failed", module=module_path, error=str(e))
            raise
        added = set(self._tools.keys()) - before
        log.info("plugin_loaded", module=module_path, new_tools=len(added))
        return len(added)

    def load_plugins(self, module_paths: List[str]) -> int:
        total = 0
        for mp in module_paths:
            try:
                total += self.load_plugin(mp)
            except Exception:
                # load_plugin already logged — keep going so one bad plugin
                # doesn't kill the whole registry.
                continue
        return total


# --------------------------------------------------------------------
# Default process-wide singleton
# --------------------------------------------------------------------

_default_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Return the process-wide ToolRegistry."""
    return _default_registry
