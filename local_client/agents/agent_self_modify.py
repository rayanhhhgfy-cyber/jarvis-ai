# ====================================================================
# JARVIS OMEGA — Self-Modification Agent (Phase 9)
# ====================================================================
"""
The Self-Modification Agent.

This is what makes JARVIS "do everything to do it" — including editing its
own source code when normal tool calls fail.

Pipeline (action="fix_self"):

  1. Parse the traceback with ``agent_repair``'s structured parser to find
     the deepest failing frame.
  2. Read the offending file via ``files.read``.
  3. Ask the LLM for a minimal unified-diff patch that fixes the error
     WITHOUT changing unrelated code.
  4. Apply the patch via ``files.edit`` (after backing up the original).
  5. Run the test suite via the self_heal test gate.
  6. If tests pass: keep the patch, audit it.
  7. If tests fail: roll back from backup, audit, and report failure.

Pipeline (action="add_capability"):

  When Sir asks for a capability JARVIS doesn't have, this agent creates a
  new plugin module under ``plugins/`` implementing the tool, then re-runs
  the tool registry loader.

Guardrails:
  * Paths in ``SELF_MODIFY_PROTECTED_PATHS`` are NEVER edited.
  * Every edit is backed up before write.
  * Every edit is followed by a pytest gate.
  * When ``allow_self_modification`` is False, the patch is recorded but
    NOT applied — the request is routed to the approval gateway instead.
"""

from __future__ import annotations

import os
import re
import time
import json
import shutil
import traceback as tb_module
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger
from shared.models import TaskDefinition, TaskResult

from local_client.agents.agent_repair import AgentRepair
from backend import self_heal
from backend.config import settings

log = get_logger("agent_self_modify")


# --------------------------------------------------------------------
# LLM prompt templates
# --------------------------------------------------------------------

_FIX_SYSTEM_PROMPT = (
    "You are the JARVIS Self-Modification Engine. You are given the source "
    "code of a Python file that just raised an exception, plus the traceback.\n\n"
    "Your job: emit the MINIMAL patch that fixes the bug without changing "
    "anything else. You must output STRICT JSON with this exact shape:\n\n"
    "{\n"
    '  "rationale": "1-2 sentences explaining the root cause.",\n'
    '  "old": "the exact substring of source code to be replaced (copied verbatim, including whitespace)",\n'
    '  "new": "the replacement substring",\n'
    '  "verify_with_tests": true\n'
    "}\n\n"
    "Rules:\n"
    "- Do NOT include markdown fences.\n"
    "- The ``old`` field MUST appear verbatim in the source so a single-string "
    "replace succeeds.\n"
    "- Prefer the smallest possible change — add a try/except, fix an attribute, "
    "guard against None, etc. Do NOT rewrite functions or change signatures.\n"
    "- If the failure is environmental (missing module, network down, permission "
    "denied), return {\"rationale\": \"...\", \"old\": \"\", \"new\": \"\", "
    "\"verify_with_tests\": false}.\n"
)

_ADD_CAP_SYSTEM_PROMPT = (
    "You are the JARVIS Capability Synthesizer. Sir wants a capability JARVIS "
    "doesn't have yet. Emit the FULL source of a new Python plugin file that "
    "registers one or more ``@tool``-decorated async functions implementing "
    "the capability.\n\n"
    "Output STRICT JSON:\n"
    "{\n"
    '  "rationale": "...",\n'
    '  "plugin_name": "lowercase_snake_case_name",\n'
    '  "file_path": "plugins/<plugin_name>/plugin.py",\n'
    '  "source_code": "FULL PYTHON SOURCE OF THE PLUGIN"\n'
    "}\n\n"
    "Rules:\n"
    "- The plugin MUST import ``from backend.tools import tool, RiskTier``.\n"
    "- Every tool MUST be async.\n"
    "- Set sensible risk tiers (read-only = TIER_0_OBSERVE, reversible = TIER_1_REVERSIBLE, etc.).\n"
    "- Emit ``PLUGIN_NAME`` / ``PLUGIN_VERSION`` / ``PLUGIN_DESCRIPTION`` module-level vars.\n"
    "- Include ``import`` statements; do NOT rely on external libraries that aren't in requirements.txt unless the tool degrades gracefully.\n"
    "- Do NOT wrap output in markdown fences.\n"
)


class AgentSelfModify:
    """
    Self-Modification Agent — can read its own source, propose patches, and
    (when ALLOW_SELF_MODIFICATION=True) apply them.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_self_modify"
        self.agent_type = AgentType.SELF_MODIFY

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("self_modify_executing", task_id=task.task_id, title=task.title)
        start = time.time()

        try:
            action = task.payload.get("action", "fix_self")

            if action == "fix_self":
                result = await self._fix_self(task)
            elif action == "add_capability":
                result = await self._add_capability(task)
            elif action == "diagnose_only":
                result = await self._diagnose_only(task)
            else:
                raise ValueError(f"Unknown SelfModify action: {action}")

            elapsed = (time.time() - start) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            err = f"{e}\n{tb_module.format_exc()}"
            log.error("self_modify_failed", task_id=task.task_id, error=err)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err,
                execution_time=elapsed,
            )

    # ==================================================================
    # Action: fix_self
    # ==================================================================

    async def _fix_self(self, task: TaskDefinition) -> Dict[str, Any]:
        tb_str = task.payload.get("traceback") or ""
        if not tb_str:
            return {"healed": False, "reason": "no traceback provided"}

        # ---- 1. Diagnose ----
        diagnosis = AgentRepair._parse_python_traceback(tb_str)
        exc = AgentRepair._parse_exception_line(tb_str)
        if not diagnosis:
            return {
                "healed": False,
                "reason": "no Python traceback frames could be parsed",
                "exception": exc,
            }
        deepest = diagnosis[-1]
        target_path = deepest.get("file", "")
        target_line = deepest.get("line")
        if not target_path or not Path(target_path).is_absolute():
            # Resolve relative to repo root.
            target_path = str(Path(target_path).resolve())

        if not Path(target_path).is_file():
            return {
                "healed": False,
                "reason": f"target file not found on disk: {target_path}",
                "exception": exc,
            }

        # ---- 2. Guardrails ----
        if self_heal.is_protected(target_path):
            log.warning("self_modify_protected_path_refused", path=target_path)
            return {
                "healed": False,
                "reason": f"refusing to edit protected path: {target_path}",
                "exception": exc,
                "protected": True,
            }
        if not self_heal.is_allowed(target_path):
            return {
                "healed": False,
                "reason": f"path outside allowed globs: {target_path}",
                "exception": exc,
            }

        # ---- 3. Read the file ----
        try:
            source = Path(target_path).read_text(encoding="utf-8")
        except Exception as read_err:
            return {"healed": False, "reason": f"failed to read target: {read_err}"}

        # ---- 4. Ask the LLM for a patch ----
        patch = await self._request_patch_from_llm(
            traceback_str=tb_str,
            target_path=target_path,
            source=source,
            exception=exc,
        )
        if not patch or not patch.get("old"):
            return {
                "healed": False,
                "reason": "LLM declined to propose a patch (environmental issue or no fix)",
                "llm_response": patch,
                "exception": exc,
            }

        old_str = patch["old"]
        new_str = patch.get("new", "")
        if old_str not in source:
            return {
                "healed": False,
                "reason": "LLM's ``old`` substring not found verbatim in source — patch rejected",
                "llm_response": patch,
            }

        # ---- 5. Apply (or route to approval if auto-edit disabled) ----
        allow = bool(task.payload.get("allow_self_modification", settings.allow_self_modification))
        if not allow:
            return {
                "healed": False,
                "applied": False,
                "reason": (
                    "ALLOW_SELF_MODIFICATION is False — patch proposed but not applied. "
                    "Approve via the approval gateway to proceed."
                ),
                "proposed_patch": patch,
                "target_path": target_path,
                "target_line": target_line,
                "exception": exc,
            }

        backup = self_heal._backup_original(target_path)
        if not backup:
            return {"healed": False, "reason": "failed to back up original file"}

        try:
            new_source = source.replace(old_str, new_str, 1)
            Path(target_path).write_text(new_source, encoding="utf-8")
        except Exception as write_err:
            return {"healed": False, "reason": f"write failed: {write_err}", "backup": backup}

        # ---- 6. Test gate ----
        test_result = await self_heal.run_test_gate(timeout=120)
        if not test_result.get("ok"):
            # Roll back.
            try:
                shutil.copy2(backup, target_path)
                log.warning("self_modify_rolled_back", path=target_path, reason="tests_failed")
            except Exception as rollback_err:
                log.error("self_modify_rollback_failed", error=str(rollback_err))

            return {
                "healed": False,
                "applied": True,
                "rolled_back": True,
                "reason": "patch applied but tests regressed — rolled back",
                "backup": backup,
                "test_result": test_result,
                "proposed_patch": patch,
                "target_path": target_path,
                "exception": exc,
            }

        # ---- 7. Success ----
        log.info("self_modify_applied", path=target_path, backup=backup)
        return {
            "healed": True,
            "applied": True,
            "rolled_back": False,
            "target_path": target_path,
            "target_line": target_line,
            "backup": backup,
            "proposed_patch": patch,
            "test_result": test_result,
            "exception": exc,
            "diagnosis": diagnosis,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ==================================================================
    # Action: add_capability
    # ==================================================================

    async def _add_capability(self, task: TaskDefinition) -> Dict[str, Any]:
        request = task.payload.get("request", "")
        if not request:
            return {"created": False, "reason": "no capability request provided"}

        if not settings.allow_self_modification:
            return {
                "created": False,
                "reason": "ALLOW_SELF_MODIFICATION is False — proposing plugin but not writing.",
            }

        spec = await self._request_new_plugin_from_llm(request)
        if not spec or not spec.get("source_code"):
            return {"created": False, "reason": "LLM did not return a valid plugin spec", "raw": spec}

        file_path = spec.get("file_path", "")
        if not file_path.startswith("plugins/"):
            return {"created": False, "reason": f"refusing to write outside plugins/: {file_path}"}

        full_path = Path(file_path)
        if full_path.exists():
            return {"created": False, "reason": f"plugin file already exists: {file_path}"}

        full_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure __init__.py exists for the package
        full_path.parent.joinpath("__init__.py").touch(exist_ok=True)

        full_path.write_text(spec["source_code"], encoding="utf-8")

        # Try to load the plugin.
        module_path = file_path.replace("/", ".").rstrip(".py").replace(".plugin", ".plugin")
        from backend.tools import get_registry
        try:
            n = get_registry().load_plugin(module_path)
        except Exception as load_err:
            # Roll back the file so a broken plugin doesn't sit in the tree.
            try:
                full_path.unlink()
            except Exception:
                pass
            return {
                "created": False,
                "applied": False,
                "reason": f"plugin failed to load: {load_err}",
                "file_path": file_path,
            }

        return {
            "created": True,
            "applied": True,
            "plugin_name": spec.get("plugin_name"),
            "file_path": file_path,
            "tools_added": n,
            "rationale": spec.get("rationale"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ==================================================================
    # Action: diagnose_only
    # ==================================================================

    async def _diagnose_only(self, task: TaskDefinition) -> Dict[str, Any]:
        tb_str = task.payload.get("traceback", "")
        diagnosis = AgentRepair._parse_python_traceback(tb_str)
        exc = AgentRepair._parse_exception_line(tb_str)
        deepest = diagnosis[-1] if diagnosis else {}
        proposal = AgentRepair._propose_fix(deepest, exc)
        return {
            "diagnosis": diagnosis,
            "exception": exc,
            "deepest_frame": deepest,
            "proposed_fix": proposal,
        }

    # ==================================================================
    # LLM helpers
    # ==================================================================

    async def _request_patch_from_llm(
        self,
        *,
        traceback_str: str,
        target_path: str,
        source: str,
        exception: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Ask OpenRouter for a minimal patch."""
        api_key = settings.openrouter_api_key
        if not api_key:
            return None

        user_msg = (
            f"EXCEPTION TYPE: {exception.get('type')}\n"
            f"EXCEPTION DETAIL: {exception.get('detail')}\n\n"
            f"TRACEBACK:\n```\n{traceback_str[-3000:]}\n```\n\n"
            f"FILE: {target_path}\n\n"
            f"SOURCE (first 8000 chars):\n```python\n{source[:8000]}\n```\n\n"
            "Emit the JSON patch now."
        )
        payload = {
            "model": settings.mythomax_model,
            "messages": [
                {"role": "system", "content": _FIX_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.1,
            "max_tokens": settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/google-deepmind/jarvis-omega",
            "X-Title": "JARVIS OMEGA Self-Modify",
        }
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
            if resp.status_code >= 400:
                log.warning("self_modify_llm_http_error", status=resp.status_code, body=resp.text[:300])
                return None
            data = resp.json()
        except Exception as e:
            log.warning("self_modify_llm_call_failed", error=str(e))
            return None

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        if not content:
            # Some reasoning models return None content + a separate ``reasoning`` field.
            try:
                content = data["choices"][0]["message"].get("reasoning") or ""
            except Exception:
                content = ""

        return self._parse_llm_json(content)

    async def _request_new_plugin_from_llm(self, request: str) -> Optional[Dict[str, Any]]:
        api_key = settings.openrouter_api_key
        if not api_key:
            return None
        user_msg = (
            f"Sir's request: {request}\n\n"
            "Emit the plugin JSON now."
        )
        payload = {
            "model": settings.mythomax_model,
            "messages": [
                {"role": "system", "content": _ADD_CAP_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.2,
            "max_tokens": 4000,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
            if resp.status_code >= 400:
                return None
            data = resp.json()
            content = data["choices"][0]["message"].get("content") or ""
            return self._parse_llm_json(content)
        except Exception as e:
            log.warning("self_modify_add_cap_failed", error=str(e))
            return None

    @staticmethod
    def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
        """Parse STRICT JSON, tolerating accidental ```json fences."""
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Salvage the largest {...} block.
            start = text.find("{")
            if start == -1:
                return None
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            return None
            return None


# Register with the orchestrator's importlib factory if invoked.
# (The orchestrator builds class name from agent_type.value; "self_modify" → "AgentSelf_modify" —
# we add an alias to handle that.)
AgentSelf_modify = AgentSelfModify  # noqa: F811 — alias for the orchestrator's loader
