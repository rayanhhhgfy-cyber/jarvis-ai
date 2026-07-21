# ====================================================================
# JARVIS OMEGA — Tool Registry Tests (Phase 8)
# ====================================================================
"""
Verifies the @tool decorator, the registry singleton, the executor's
approval-gateway integration, and that every shipped plugin loads cleanly.
"""

from __future__ import annotations

import pytest

from backend.tools import tool, get_registry, Tool, RiskTier
from backend.tools.registry import ToolRegistry


# --------------------------------------------------------------------
# Decorator + registration
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_decorator_registers_function():
    """@tool with an explicit registry should add the tool."""
    reg = ToolRegistry()

    @tool(
        name="test.echo",
        description="echo",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        risk_tier=RiskTier.TIER_0_OBSERVE,
        registry=reg,
    )
    async def echo(msg: str = "") -> str:
        return msg

    # The decorator returns the Tool (function-like).
    assert isinstance(echo, Tool)
    assert reg.get("test.echo") is echo


def test_tool_name_must_be_dotted():
    """Names without a dot are rejected so categories stay clean."""
    reg = ToolRegistry()

    async def f() -> None:
        return None

    with pytest.raises(ValueError):
        Tool(name="badname", description="d", func=f)


def test_tool_must_be_async():
    """Sync functions are rejected — tool execution is always awaitable."""
    with pytest.raises(TypeError):
        Tool(
            name="bad.sync",
            description="d",
            func=lambda: None,  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------
# OpenAI schema rendering
# --------------------------------------------------------------------

def test_openai_schema_has_expected_shape():
    reg = ToolRegistry()

    @tool(
        name="x.y",
        description="does y to x",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
        risk_tier=RiskTier.TIER_0_OBSERVE,
        registry=reg,
    )
    async def y(a: str) -> str:
        return a

    schema = y.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "x.y"
    assert schema["function"]["parameters"]["properties"]["a"]["type"] == "string"


# --------------------------------------------------------------------
# Plugin loading — verifies every shipped plugin loads
# --------------------------------------------------------------------

def test_all_seed_plugins_load():
    """Every shipped plugin must load and register tools on the global registry."""
    reg = get_registry()
    reg.load_plugins([
        "plugins.core_dev.plugin",
        "plugins.code_sandbox.plugin",
        "plugins.documents.plugin",
        "plugins.communication.plugin",
        "plugins.media_gen.plugin",
        "plugins.mobile.plugin",
        "plugins.smart_home.plugin",
        "plugins.cloud.plugin",
        "plugins.atxp.plugin",
    ])
    # Idempotent: re-importing an already-loaded module is a no-op for the
    # @tool decorators, so we check the GLOBAL registry's total tool count
    # rather than the return value of load_plugins.
    all_tools = reg.all_tools()
    assert len(all_tools) >= 30
    categories = {t.category for t in all_tools}
    # The 8 user-selected categories + atxp must all be present.
    assert {
        "filesystem", "shell", "git", "code", "documents",
        "communication", "media", "mobile", "smart_home", "cloud", "atxp",
    } <= categories


def test_registry_returns_schemas_for_llm():
    """``schemas_for_llm`` must include at least the core_dev tools."""
    reg = get_registry()
    schemas = reg.schemas_for_llm()
    assert any(s["function"]["name"] == "files.read" for s in schemas)


# --------------------------------------------------------------------
# Executor — approval gate integration
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tier_0_tool_runs_without_approval():
    """Tier 0 tools must NOT consult the approval gateway."""
    from backend.tools.executor import ToolExecutor

    # Register a Tier 0 tool on the global registry.
    @tool(
        name="test.tier0",
        description="harmless",
        risk_tier=RiskTier.TIER_0_OBSERVE,
    )
    async def tier0() -> str:
        return "ok"

    ex = ToolExecutor()
    # Deliberately do NOT inject approval_gateway — tier 0 must not need it.
    result = await ex.invoke("test.tier0", {}, session_id="t")
    assert result["status"] == "completed"
    assert result["result"] == "ok"


@pytest.mark.asyncio
async def test_tier_3_tool_without_gateway_is_blocked():
    """Tier 3 tools cannot execute when no approval gateway is wired."""
    from backend.tools.executor import ToolExecutor

    @tool(
        name="test.tier3",
        description="destructive",
        risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    )
    async def tier3() -> str:
        return "ran"

    ex = ToolExecutor()
    # No approval_gateway injected.
    result = await ex.invoke("test.tier3", {}, session_id="t")
    assert result["status"] == "rejected"
