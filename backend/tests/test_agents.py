# ====================================================================
# JARVIS OMEGA — Agent Tests (Phase 4 implementations)
# ====================================================================
"""
Tests for the promoted stub agents: security scanner, planner, repair parser,
testing agent discovery/parse.

These use only local fixtures and mocks — no network calls.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.constants import AgentType
from shared.models import TaskDefinition
from local_client.agents.agent_security import AgentSecurity, _SECRET_PATTERNS
from local_client.agents.agent_planner import AgentPlanner
from local_client.agents.agent_repair import AgentRepair
from local_client.agents.agent_testing import AgentTesting


# ----------------------------------------------------
# Security scanner
# ----------------------------------------------------

def test_security_agent_has_all_required_patterns():
    """Ensure we ship scanners for the major cloud/source-control providers."""
    names = {name for name, _, _ in _SECRET_PATTERNS}
    required = {
        "AWS Access Key ID",
        "AWS Secret Access Key",
        "OpenRouter API Key",
        "OpenAI API Key",
        "GitHub Personal Access Token",
        "Slack Bot Token",
        "Stripe Secret Key",
        "Google API Key",
        "PEM Private Key Block",
    }
    missing = required - names
    assert not missing, f"Missing scanner patterns: {missing}"


@pytest.mark.asyncio
async def test_security_scanner_detects_real_secrets(tmp_path: Path):
    sample = tmp_path / "leak.py"
    sample.write_text(
        'AWS = "AKIAIOSFODNN7EXAMPLE"\n'
        'OR_KEY = "sk-or-v1-' + ("a" * 60) + '"\n'
        'GHP = "ghp_' + ("b" * 36) + '"\n'
        "password = \"supersecret\"\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n"
    )
    task = TaskDefinition(
        title="scan",
        description="scan tmp",
        agent_type=AgentType.SECURITY,
        payload={"action": "scan", "scan_path": str(tmp_path)},
    )
    result = await AgentSecurity().execute_task(task)
    assert result.status.value == "completed"
    types = {leak["type"] for leak in result.result["all_leaks"]}
    assert "AWS Access Key ID" in types
    assert "OpenRouter API Key" in types
    assert "GitHub Personal Access Token" in types
    assert "PEM Private Key Block" in types
    # Snippets must be redacted — the report itself must not contain the full secret.
    for leak in result.result["all_leaks"]:
        assert "redacted" in leak["snippet"] or len(leak["snippet"]) < 32


@pytest.mark.asyncio
async def test_security_scanner_skips_binary_and_large_files(tmp_path: Path):
    # Binary file
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02AKIAIOSFODNN7EXAMPLE")
    # Oversize text
    big = tmp_path / "huge.txt"
    big.write_text("AKIAIOSFODNN7EXAMPLE\n" * 100000)

    task = TaskDefinition(
        title="scan",
        description="scan",
        agent_type=AgentType.SECURITY,
        payload={"action": "scan", "scan_path": str(tmp_path)},
    )
    result = await AgentSecurity().execute_task(task)
    assert result.result["critical_count"] == 0


@pytest.mark.asyncio
async def test_security_scanner_handles_missing_path(tmp_path: Path):
    task = TaskDefinition(
        title="scan",
        description="scan",
        agent_type=AgentType.SECURITY,
        payload={"action": "scan", "scan_path": str(tmp_path / "nope")},
    )
    result = await AgentSecurity().execute_task(task)
    assert result.status.value == "completed"
    assert result.result["status"] == "scan_failed"


# ----------------------------------------------------
# Planner
# ----------------------------------------------------

def test_planner_template_fallback():
    """When the LLM is unavailable, planner must fall back to a template."""
    planner = AgentPlanner()
    steps = AgentPlanner._template_decompose("deploy the app")
    assert len(steps) >= 3
    assert all("title" in s and "agent_type" in s for s in steps)


def test_planner_strips_code_fences():
    raw = "```json\n{\"steps\": []}\n```"
    assert AgentPlanner._strip_code_fences(raw) == "{\"steps\": []}"


def test_planner_extract_json_block_handles_trailing_prose():
    text = '{"steps": [{"title": "x"}]} and then some trailing prose'
    block = AgentPlanner._extract_json_block(text)
    assert block is not None
    assert block.startswith("{") and block.endswith("}")


# ----------------------------------------------------
# Repair agent
# ----------------------------------------------------

def test_repair_parses_python_traceback():
    tb = (
        'Traceback (most recent call last):\n'
        '  File "backend/main.py", line 42, in get_health\n'
        '    return HealthSnapshot()\n'
        '  File "shared/security.py", line 75, in init_security\n'
        '    raise RuntimeError("no key")\n'
        'RuntimeError: no key'
    )
    frames = AgentRepair._parse_python_traceback(tb)
    assert len(frames) == 2
    assert frames[-1]["file"] == "shared/security.py"
    assert frames[-1]["line"] == 75
    assert frames[-1]["function"] == "init_security"

    exc = AgentRepair._parse_exception_line(tb)
    assert exc["type"] == "RuntimeError"
    assert exc["detail"] == "no key"


def test_repair_propose_fix_dispatches_by_exception_type():
    proposals = [
        AgentRepair._propose_fix({}, {"type": "ImportError", "detail": ""}),
        AgentRepair._propose_fix({}, {"type": "KeyError", "detail": ""}),
        AgentRepair._propose_fix({}, {"type": "ZeroDivisionError", "detail": ""}),
        AgentRepair._propose_fix({}, {"type": "FileNotFoundError", "detail": ""}),
    ]
    assert any("import" in p.lower() for p in proposals)
    assert any("key" in p.lower() or "container" in p.lower() for p in proposals)
    assert any("zero" in p.lower() for p in proposals)
    assert any("file" in p.lower() for p in proposals)


@pytest.mark.asyncio
async def test_repair_analyze_returns_structured_result():
    task = TaskDefinition(
        title="analyze",
        description="parse tb",
        agent_type=AgentType.REPAIR,
        payload={
            "action": "analyze",
            "traceback": (
                'Traceback (most recent call last):\n'
                '  File "x.py", line 10, in f\n'
                'ValueError: bad'
            ),
        },
    )
    result = await AgentRepair().execute_task(task)
    assert result.status.value == "completed"
    data = result.result
    assert data["isolated_file"] == "x.py"
    assert data["isolated_line"] == 10
    assert data["exception_type"] == "ValueError"


# ----------------------------------------------------
# Testing agent
# ----------------------------------------------------

@pytest.mark.asyncio
async def test_testing_discovers_pytest_files(tmp_path: Path):
    (tmp_path / "test_foo.py").write_text("def test_x(): pass")
    (tmp_path / "bar_test.py").write_text("def test_y(): pass")
    (tmp_path / "helper.py").write_text("print('hi')")
    task = TaskDefinition(
        title="discover",
        description="find tests",
        agent_type=AgentType.TESTING,
        payload={"action": "discover", "search_dir": str(tmp_path)},
    )
    result = await AgentTesting().execute_task(task)
    files = result.result["test_files"]
    assert any(p.endswith("test_foo.py") for p in files)
    assert any(p.endswith("bar_test.py") for p in files)
    assert not any(p.endswith("helper.py") for p in files)


def test_testing_parses_pytest_summary():
    sample_stdout = (
        "============================= test session starts ==============================\n"
        "collected 4 items\n\n"
        "backend/tests/test_a.py::test_one PASSED                           [ 25%]\n"
        "backend/tests/test_a.py::test_two FAILED                           [ 50%]\n"
        "backend/tests/test_a.py::test_three SKIPPED (reason)               [ 75%]\n"
        "backend/tests/test_a.py::test_four PASSED                          [100%]\n\n"
        "=================================== FAILURES ===================================\n"
        "_______________________________ test_two ___________________________________\n"
        "assert 1 == 2\n"
        "============================= short test summary info ==============================\n"
        "FAILED backend/tests/test_a.py::test_two - assert 1 == 2\n"
        "======================== 2 passed, 1 failed, 1 skipped in 0.5s ========================\n"
    )
    parsed = AgentTesting._parse_pytest_output(sample_stdout, "")
    assert parsed["summary"]["passed"] == 2
    assert parsed["summary"]["failed"] == 1
    assert parsed["summary"]["skipped"] == 1
    assert parsed["summary"]["total"] == 4
    assert len(parsed["failures"]) == 1
    assert "test_two" in parsed["failures"][0]["test"]
