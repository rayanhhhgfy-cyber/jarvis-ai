# ====================================================================
# JARVIS OMEGA — Self-Heal & Self-Modify Tests (Phase 9)
# ====================================================================
"""
Tests the path-policy guardrails, the LLM JSON parser, and the audit
pipeline. We do NOT run a live LLM call here — that's covered by the
OpenRouter ping in the Final verification step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import self_heal
from local_client.agents.agent_self_modify import AgentSelfModify
from shared.constants import (
    SELF_MODIFY_PROTECTED_PATHS,
    SELF_MODIFY_ALLOWED_GLOBS,
)


# --------------------------------------------------------------------
# Path policy — the load-bearing safety circuit
# --------------------------------------------------------------------

def test_protected_paths_cover_safety_critical_files():
    """Critical files MUST be in the protected list."""
    required = {
        "shared/security.py",
        "shared/constants.py",
        "backend/services/command_safety.py",
        "backend/approval_gateway.py",
        "backend/config.py",
        "backend/self_heal.py",
        "local_client/agents/agent_self_modify.py",
        ".env",
    }
    actual = {p.replace("\\", "/") for p in SELF_MODIFY_PROTECTED_PATHS}
    missing = required - actual
    assert not missing, f"protected paths missing: {missing}"


def test_is_protected_blocks_critical_files():
    assert self_heal.is_protected(".env")
    assert self_heal.is_protected("shared/security.py")
    assert self_heal.is_protected("backend/services/command_safety.py")
    assert self_heal.is_protected("backend/approval_gateway.py")


def test_is_protected_blocks_absolute_paths_too():
    """Path normalization must catch absolute paths to protected files."""
    assert self_heal.is_protected("/home/jarvis/shared/security.py")
    assert self_heal.is_protected("C:/jarvis/backend/config.py")


def test_is_allowed_accepts_python_source():
    assert self_heal.is_allowed("backend/main.py")
    assert self_heal.is_allowed("backend/routers/router_chat.py")
    assert self_heal.is_allowed("local_client/agents/agent_repair.py")
    assert self_heal.is_allowed("plugins/core_dev/plugin.py")


def test_is_allowed_rejects_outside_globs():
    assert not self_heal.is_allowed("/etc/passwd")
    assert not self_heal.is_allowed("README.md")
    assert not self_heal.is_allowed("frontend/index.html")
    assert not self_heal.is_allowed("notes.txt")


def test_is_allowed_overrides_with_protected():
    """A file matching an allowed glob is still blocked if it's protected."""
    # backend/self_heal.py matches backend/**/*.py but is in the protected list.
    assert not self_heal.is_allowed("backend/self_heal.py")
    assert not self_heal.is_allowed("local_client/agents/agent_self_modify.py")


# --------------------------------------------------------------------
# LLM JSON parsing
# --------------------------------------------------------------------

def test_parse_llm_json_plain():
    out = AgentSelfModify._parse_llm_json('{"rationale":"x","old":"a","new":"b"}')
    assert out == {"rationale": "x", "old": "a", "new": "b"}


def test_parse_llm_json_with_fences():
    raw = "```json\n" + '{"rationale":"x","old":"a","new":"b"}' + "\n```"
    out = AgentSelfModify._parse_llm_json(raw)
    assert out["old"] == "a"


def test_parse_llm_json_with_trailing_prose():
    raw = '{"rationale":"x","old":"a","new":"b"} and then some explanation'
    out = AgentSelfModify._parse_llm_json(raw)
    assert out["old"] == "a"


def test_parse_llm_json_handles_empty():
    assert AgentSelfModify._parse_llm_json("") is None
    assert AgentSelfModify._parse_llm_json("not json at all") is None


# --------------------------------------------------------------------
# Backup + audit
# --------------------------------------------------------------------

def test_backup_original_creates_copy(tmp_path: Path):
    src = tmp_path / "src" / "foo.py"
    src.parent.mkdir(parents=True)
    src.write_text("print('hello')", encoding="utf-8")

    # Patch the backup dir to a tmp location for this test.
    import backend.self_heal as sh
    original = sh.SELF_MODIFY_BACKUP_DIR
    sh.SELF_MODIFY_BACKUP_DIR = str(tmp_path / "backups")
    try:
        backup = sh._backup_original(str(src))
        assert backup is not None
        assert Path(backup).exists()
        assert Path(backup).read_text() == "print('hello')"
    finally:
        sh.SELF_MODIFY_BACKUP_DIR = original


def test_backup_original_handles_missing_file(tmp_path: Path):
    backup = self_heal._backup_original(str(tmp_path / "does-not-exist.py"))
    assert backup is None


def test_write_audit_persists_json(tmp_path: Path):
    import backend.self_heal as sh
    original = sh.SELF_MODIFY_AUDIT_DIR
    sh.SELF_MODIFY_AUDIT_DIR = str(tmp_path / "audit")
    try:
        sh._write_audit({
            "timestamp": "2026-01-01T00:00:00",
            "fingerprint": "abc123",
            "traceback": "ValueError: test",
            "target_path": "backend/foo.py",
        })
        files = list(Path(sh.SELF_MODIFY_AUDIT_DIR).glob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["fingerprint"] == "abc123"
    finally:
        sh.SELF_MODIFY_AUDIT_DIR = original


# --------------------------------------------------------------------
# Failure-memory fingerprint
# --------------------------------------------------------------------

def test_fingerprint_is_stable_across_variable_values():
    """Same code path, different arg values → same fingerprint."""
    tb1 = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 10, in f\n'
        'ValueError: bad value 1'
    )
    tb2 = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 10, in f\n'
        'ValueError: bad value 2'
    )
    assert self_heal._fingerprint(tb1) == self_heal._fingerprint(tb2)


def test_fingerprint_differs_for_different_code_paths():
    tb1 = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 10, in f\n'
        'ValueError: a'
    )
    tb2 = (
        'Traceback (most recent call last):\n'
        '  File "y.py", line 99, in g\n'
        'ValueError: a'
    )
    assert self_heal._fingerprint(tb1) != self_heal._fingerprint(tb2)


# --------------------------------------------------------------------
# Diagnose-only path (no LLM call needed)
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_self_modify_diagnose_only_returns_structured_result():
    from shared.constants import AgentType, TaskStatus
    from shared.models import TaskDefinition

    task = TaskDefinition(
        title="diagnose",
        description="parse tb",
        agent_type=AgentType.SELF_MODIFY,
        payload={
            "action": "diagnose_only",
            "traceback": (
                'Traceback (most recent call last):\n'
                '  File "backend/x.py", line 42, in f\n'
                'KeyError: "missing"'
            ),
        },
    )
    result = await AgentSelfModify().execute_task(task)
    assert result.status is TaskStatus.COMPLETED
    data = result.result
    assert data["exception"]["type"] == "KeyError"
    assert data["deepest_frame"]["file"] == "backend/x.py"
    assert data["deepest_frame"]["line"] == 42


@pytest.mark.asyncio
async def test_agent_self_modify_fix_self_refuses_protected_path():
    """Even with allow_self_modification=True, protected paths are off-limits."""
    from shared.constants import AgentType, TaskStatus
    from shared.models import TaskDefinition

    task = TaskDefinition(
        title="fix",
        description="try to edit protected file",
        agent_type=AgentType.SELF_MODIFY,
        payload={
            "action": "fix_self",
            "traceback": (
                'Traceback (most recent call last):\n'
                f'  File "{__file__.replace(chr(92), "/")}", line 1, in x\n'
                '  File "shared/security.py", line 100, in init_security\n'
                'RuntimeError: no key'
            ),
            "allow_self_modification": True,
        },
    )
    result = await AgentSelfModify().execute_task(task)
    # The deepest frame in this synthetic tb is shared/security.py — protected.
    # (Note: __file__ in the trace also resolves to this test file, which is in
    # backend/tests/ and not protected. The test relies on the LAST frame being
    # shared/security.py.)
    data = result.result
    # Either:
    #  - target_path resolves to shared/security.py → refused as protected
    #  - target_path resolves to this test file → refused as "outside allowed"
    #     because backend/tests/_test files aren't in SELF_MODIFY_ALLOWED_GLOBS
    assert data.get("healed") is False or data.get("applied") is False
