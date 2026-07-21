# ====================================================================
# JARVIS OMEGA — Code Sandbox Plugin
# ====================================================================
"""
Phase 8 seed plugin: run Python / Node / Go code on the host.

Per Sir's explicit direction: approval-only, NO Docker / firejail isolation.
A misclicked approval is therefore equivalent to running the snippet in your
own shell. The approval gateway + audit log are the only guards.

All ``code.run_*`` tools are RiskTier 2 (System) — Sir approves once per
session per language, then JARVIS can iterate quickly.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from backend.tools import tool, RiskTier


async def _run_executable(argv: list[str], source: str, suffix: str, timeout: float) -> Dict[str, Any]:
    """Write source to a temp file, execute argv, capture output."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as tf:
        tf.write(source)
        tmp_path = tf.name

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout}s.",
                "timed_out": True,
            }
        return {
            "exit_code": proc.returncode or 0,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "file": tmp_path,
        }
    finally:
        # Best-effort cleanup of the temp file.
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


@tool(
    name="code.run_python",
    description="Execute a Python snippet on the host. Returns exit_code, stdout, stderr.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Python source code to execute."},
            "timeout": {"type": "number", "default": 30},
        },
        "required": ["source"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="code",
)
async def code_run_python(source: str, timeout: float = 30.0) -> Dict[str, Any]:
    return await _run_executable([sys.executable, "-"], source, ".py", timeout)


@tool(
    name="code.run_node",
    description="Execute a Node.js snippet on the host. Requires node on PATH.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "timeout": {"type": "number", "default": 30},
        },
        "required": ["source"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="code",
)
async def code_run_node(source: str, timeout: float = 30.0) -> Dict[str, Any]:
    # node can't read from stdin via argv like python -; write to temp file.
    return await _run_executable(["node"], source, ".js", timeout)


@tool(
    name="code.run_go",
    description="Execute a Go snippet on the host via ``go run``. Requires go on PATH.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "timeout": {"type": "number", "default": 60},
        },
        "required": ["source"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="code",
)
async def code_run_go(source: str, timeout: float = 60.0) -> Dict[str, Any]:
    return await _run_executable(["go", "run"], source, ".go", timeout)


@tool(
    name="code.lint_python",
    description="Run ruff check on a directory. Returns stdout from ruff.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="code",
)
async def code_lint_python(path: str = ".") -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "ruff", "check", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return {
        "exit_code": proc.returncode or 0,
        "stdout": out.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
    }


PLUGIN_NAME = "code_sandbox"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Run Python / Node / Go snippets on the host (approval-only, no sandbox)."
