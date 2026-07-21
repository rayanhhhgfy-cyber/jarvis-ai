# ====================================================================
# JARVIS OMEGA — Core Dev Plugin
# ====================================================================
"""
Phase 8 seed plugin: filesystem, shell, and git tools.

These cover the daily-driver capabilities JARVIS needs to act as a software
engineer: reading/writing/editing files, running shell commands (with safety
gate), and basic git operations.

Browser tools live in a separate plugin (``plugins.browser``) because
Playwright is an optional dependency.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from backend.tools import tool, RiskTier


# --------------------------------------------------------------------
# Filesystem tools (Tier 0 / 1)
# --------------------------------------------------------------------

@tool(
    name="files.read",
    description="Read a UTF-8 text file from the workspace. Returns the file contents as a string.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="filesystem",
)
async def files_read(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    # Cap at 1 MiB so a giant log can't OOM the agent.
    if p.stat().st_size > 1 * 1024 * 1024:
        raise ValueError(f"file too large (>1MiB): {path}")
    return p.read_text(encoding="utf-8", errors="replace")


@tool(
    name="files.write",
    description="Write text content to a file. Overwrites the file if it exists; creates parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="filesystem",
)
async def files_write(path: str, content: str) -> Dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p.resolve()), "bytes": len(content)}


@tool(
    name="files.edit",
    description="Replace one exact substring with another inside a file. Fails if the old string is not present or appears more than once unless replace_all=true.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
        },
        "required": ["path", "old", "new"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="filesystem",
)
async def files_edit(path: str, old: str, new: str, replace_all: bool = False) -> Dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("old string not found in file")
    if count > 1 and not replace_all:
        raise ValueError(f"old string appears {count} times; pass replace_all=true")
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    p.write_text(updated, encoding="utf-8")
    return {"path": str(p.resolve()), "replaced": count if replace_all else 1}


@tool(
    name="files.list",
    description="List files and directories under a path. Returns a list of names (relative to the path).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "recursive": {"type": "boolean", "default": False},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="filesystem",
)
async def files_list(path: str = ".", recursive: bool = False) -> List[str]:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(path)
    if recursive:
        return [str(p.relative_to(root)) for p in root.rglob("*")]
    return [p.name for p in root.iterdir()]


@tool(
    name="files.search",
    description="Recursive grep for a regex inside files under a directory. Returns up to 50 matches with file, line number, and line content.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex pattern."},
            "path": {"type": "string", "default": "."},
            "include": {"type": "string", "description": "Filename glob filter (e.g. '*.py')."},
        },
        "required": ["pattern"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="filesystem",
)
async def files_search(pattern: str, path: str = ".", include: str = "") -> List[Dict[str, Any]]:
    import re
    rx = re.compile(pattern)
    root = Path(path)
    results: List[Dict[str, Any]] = []
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if include:
            import fnmatch
            if not fnmatch.fnmatch(fp.name, include):
                continue
        if fp.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
                                  ".mp3", ".mp4", ".wav", ".avi",
                                  ".zip", ".gz", ".tar",
                                  ".db", ".sqlite", ".pyc", ".so", ".dll", ".exe"}:
            continue
        try:
            if fp.stat().st_size > 1024 * 1024:
                continue
            for i, line in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if rx.search(line):
                    results.append({"file": str(fp), "line": i, "content": line[:200]})
                    if len(results) >= 50:
                        return results
        except Exception:
            continue
    return results


# --------------------------------------------------------------------
# Shell tool — reuses the chat-router safety validator
# --------------------------------------------------------------------

@tool(
    name="shell.run",
    description="Execute a shell command on the workstation. Returns exit_code, stdout, stderr. DANGEROUS commands are routed to the approval gateway before execution.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command string to execute."},
            "timeout": {"type": "number", "default": 30, "description": "Seconds before the command is killed."},
            "cwd": {"type": "string", "description": "Working directory."},
        },
        "required": ["command"],
    },
    risk_tier=RiskTier.TIER_2_SYSTEM,
    category="shell",
)
async def shell_run(command: str, timeout: float = 30.0, cwd: str = "") -> Dict[str, Any]:
    from backend.services.command_safety import command_safety, VerdictLevel
    verdict = command_safety.validate(command)
    if verdict.blocked:
        return {
            "exit_code": 126,
            "stdout": "",
            "stderr": f"Command blocked by safety validator: {verdict.reason}",
            "blocked": True,
        }

    is_windows = sys.platform.startswith("win")
    argv = ["cmd", "/c", command] if is_windows else ["/bin/sh", "-c", command]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or None,
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
            "stderr": f"Command exceeded timeout of {timeout}s and was killed.",
            "timed_out": True,
        }
    return {
        "exit_code": proc.returncode or 0,
        "stdout": stdout_b.decode("utf-8", errors="replace"),
        "stderr": stderr_b.decode("utf-8", errors="replace"),
    }


# --------------------------------------------------------------------
# Git tools (Tier 0/1)
# --------------------------------------------------------------------

async def _git(args: List[str], cwd: str = ".") -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    out, err = await proc.communicate()
    return {
        "exit_code": proc.returncode or 0,
        "stdout": out.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
    }


@tool(
    name="git.status",
    description="Run ``git status`` in a repository. Returns stdout.",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "default": "."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="git",
)
async def git_status(cwd: str = ".") -> Dict[str, Any]:
    return await _git(["status", "--porcelain"], cwd=cwd)


@tool(
    name="git.diff",
    description="Run ``git diff`` to see uncommitted changes.",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "default": "."},
            "staged": {"type": "boolean", "default": False},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="git",
)
async def git_diff(cwd: str = ".", staged: bool = False) -> Dict[str, Any]:
    args = ["diff", "--cached"] if staged else ["diff"]
    return await _git(args, cwd=cwd)


@tool(
    name="git.commit",
    description="Stage all changes and create a git commit with the given message.",
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "cwd": {"type": "string", "default": "."},
            "add_all": {"type": "boolean", "default": True},
        },
        "required": ["message"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="git",
)
async def git_commit(message: str, cwd: str = ".", add_all: bool = True) -> Dict[str, Any]:
    if add_all:
        await _git(["add", "-A"], cwd=cwd)
    return await _git(["commit", "-m", message], cwd=cwd)


@tool(
    name="git.log",
    description="Show the most recent commits.",
    parameters={
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "default": "."},
            "limit": {"type": "integer", "default": 10},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="git",
)
async def git_log(cwd: str = ".", limit: int = 10) -> Dict[str, Any]:
    return await _git(["log", f"-n{limit}", "--oneline"], cwd=cwd)


# --------------------------------------------------------------------
# Plugin metadata (used by the plugin loader)
# --------------------------------------------------------------------

PLUGIN_NAME = "core_dev"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Filesystem + shell + git tools. The daily-driver capability set."
