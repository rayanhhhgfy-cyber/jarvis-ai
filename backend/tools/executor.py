# ====================================================================
# JARVIS OMEGA — Tool Executor
# ====================================================================
"""
Runs registered tools, enforcing the approval gateway for any tool at
RiskTier 2 (System) or higher.

The executor also remembers per-session "always allow" decisions so Sir
does not get nagged for the same tool twice in one conversation
(configurable via settings — see Phase 8.8 in the plan).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

from shared.constants import RiskLevel, RiskTier
from shared.logger import get_logger
from shared.models import ApprovalRequest

from backend.tools.registry import Tool, get_registry

log = get_logger("tool_executor")


class ToolExecutor:
    """
    Dispatches tool invocations.

    Approval policy:
      * Tier 0 (observe) and Tier 1 (reversible) — execute immediately, log.
      * Tier 2 (system)                          — ask once per session.
      * Tier 3 (destructive)                     — always ask.
      * Tier 4 (external side-effect)            — always ask + log to audit.
    """

    def __init__(self) -> None:
        # session_id -> set of tool names Sir has approved this session
        self._session_allowed: Dict[str, Set[str]] = {}
        # session_id -> set of tool names Sir has explicitly denied
        self._session_denied: Dict[str, Set[str]] = {}
        # immutable audit log path; one line per executed tool
        self._audit_path = Path("./storage/audit.log")
        self._approval_gateway = None  # injected at startup

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_approval_gateway(self, gw) -> None:
        self._approval_gateway = gw

    def _ensure_audit_file(self) -> None:
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            self._audit_path.touch(exist_ok=True)
        except Exception as e:
            log.warning("audit_log_init_failed", error=str(e), path=str(self._audit_path))

    # ------------------------------------------------------------------
    # Session memory
    # ------------------------------------------------------------------

    def remember_approval(self, session_id: str, tool_name: str) -> None:
        self._session_allowed.setdefault(session_id, set()).add(tool_name)
        # If previously denied, clear that.
        self._session_denied.get(session_id, set()).discard(tool_name)

    def remember_denial(self, session_id: str, tool_name: str) -> None:
        self._session_denied.setdefault(session_id, set()).add(tool_name)
        self._session_allowed.get(session_id, set()).discard(tool_name)

    def reset_session(self, session_id: str) -> None:
        self._session_allowed.pop(session_id, None)
        self._session_denied.pop(session_id, None)

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    async def invoke(
        self,
        name: str,
        arguments: Dict[str, Any],
        session_id: str = "default",
        requesting_agent: str = "router_chat",
    ) -> Dict[str, Any]:
        """
        Invoke a tool by name with the supplied arguments.

        Returns a dict with:
          * ``status``    — "completed" | "blocked" | "rejected" | "error" | "not_found"
          * ``result``    — whatever the tool returned (when completed)
          * ``error``     — message when status != completed
          * ``tool``      — the tool name
          * ``risk_tier`` — tier value
        """
        tool_obj: Optional[Tool] = get_registry().get(name)
        if tool_obj is None:
            return {"status": "not_found", "error": f"unknown tool: {name}", "tool": name}
        if not tool_obj.enabled:
            return {"status": "not_found", "error": f"tool disabled: {name}", "tool": name}

        # ---- Approval gate --------------------------------------------------
        approved = await self._check_approval(tool_obj, session_id, requesting_agent, arguments)
        if not approved:
            return {
                "status": "rejected",
                "error": f"Tool {name} was not approved by Sir.",
                "tool": name,
                "risk_tier": tool_obj.risk_tier.value,
            }

        # ---- Execute --------------------------------------------------------
        try:
            log.info("tool_invoking", tool=name, tier=tool_obj.risk_tier.value, session=session_id)
            result = await tool_obj.func(**arguments)
            self._write_audit(tool_obj, arguments, session_id, requesting_agent, "ok")
            return {
                "status": "completed",
                "result": result,
                "tool": name,
                "risk_tier": tool_obj.risk_tier.value,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("tool_failed", tool=name, error=str(exc), exc_info=True)
            self._write_audit(tool_obj, arguments, session_id, requesting_agent, f"error: {exc}")
            return {
                "status": "error",
                "error": str(exc),
                "tool": name,
                "risk_tier": tool_obj.risk_tier.value,
            }

    # ------------------------------------------------------------------
    # Approval helpers
    # ------------------------------------------------------------------

    async def _check_approval(
        self,
        tool_obj: Tool,
        session_id: str,
        requesting_agent: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Return True if the tool may execute (or has been approved this call)."""
        tier = tool_obj.risk_tier

        # Tier 0/1 — no approval needed.
        if tier in (RiskTier.TIER_0_OBSERVE, RiskTier.TIER_1_REVERSIBLE):
            return True

        # Previously denied this session?  Stay denied until reset.
        if tool_obj.name in self._session_denied.get(session_id, set()):
            return False

        # Session-memory: "ask once per tool" only applies to Tier 2 (system).
        # Tier 3+ always re-confirms.
        if (
            tier is RiskTier.TIER_2_SYSTEM
            and tool_obj.name in self._session_allowed.get(session_id, set())
        ):
            return True

        # Route to the approval gateway.
        if self._approval_gateway is None:
            log.error("approval_gateway_not_injected_tool_blocked", tool=tool_obj.name)
            return False

        risk_level = {
            RiskTier.TIER_2_SYSTEM: RiskLevel.MEDIUM,
            RiskTier.TIER_3_DESTRUCTIVE: RiskLevel.HIGH,
            RiskTier.TIER_4_EXTERNAL: RiskLevel.CRITICAL,
        }.get(tier, RiskLevel.HIGH)

        preview_args = {k: (str(v)[:120]) for k, v in arguments.items()}
        req = ApprovalRequest(
            action=f"tool.{tool_obj.name}",
            reason=f"Risk tier {tier.value}: {tool_obj.description}",
            risk_level=risk_level,
            affected_resources=list(preview_args.values())[:5],
            expected_result=f"{tool_obj.name} will execute with args {preview_args}",
            undo_possible=tier is RiskTier.TIER_2_SYSTEM,
            requesting_agent=requesting_agent,
        )
        approval_id = await self._approval_gateway.request_approval(req)
        decision = await self._approval_gateway.wait_for_approval(approval_id, timeout=300.0)
        if decision:
            # Tier 2 sticks for the session. Tier 3+ re-asks next time.
            if tier is RiskTier.TIER_2_SYSTEM:
                self.remember_approval(session_id, tool_obj.name)
            return True
        else:
            self.remember_denial(session_id, tool_obj.name)
            return False

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _write_audit(
        self,
        tool_obj: Tool,
        arguments: Dict[str, Any],
        session_id: str,
        requesting_agent: str,
        outcome: str,
    ) -> None:
        try:
            self._ensure_audit_file()
            preview = {k: (str(v)[:80]) for k, v in arguments.items()}
            line = (
                f'[{datetime.utcnow().isoformat()}]'
                f' tool="{tool_obj.name}"'
                f' tier="{tool_obj.risk_tier.value}"'
                f' agent="{requesting_agent}"'
                f' session="{session_id}"'
                f' outcome="{outcome}"'
                f' args="{preview}"\n'
            )
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception as audit_err:
            log.warning("audit_write_failed", error=str(audit_err))


# Process-wide singleton
tool_executor = ToolExecutor()
