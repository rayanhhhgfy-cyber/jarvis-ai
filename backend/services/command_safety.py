# ====================================================================
# JARVIS OMEGA — Command Safety Validator
# ====================================================================
"""
Pre-execution validation of shell commands emitted by the LLM.

This module is the gate between model-generated commands and the host shell.
It enforces three layers of defense:

1. **Length & character sanity** — reject absurdly long commands and embedded
   control characters that have no legitimate use.
2. **Hard blocklist** — `BLOCKED_COMMAND_PATTERNS` cannot be approved by anyone
   (e.g. fork bombs, dd to a whole disk).
3. **Dangerous classification** — `DANGEROUS_COMMAND_PATTERNS` are routed to the
   approval gateway; Sir decides whether they run.

Returns a `SafetyVerdict` describing what to do with the command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from shared.constants import (
    BLOCKED_COMMAND_PATTERNS,
    DANGEROUS_COMMAND_PATTERNS,
    MAX_COMMAND_LENGTH,
)
from shared.logger import get_logger

log = get_logger("command_safety")


class VerdictLevel(str, Enum):
    """What the safety validator decided about a command."""

    ALLOWED = "allowed"          # safe to execute immediately
    NEEDS_APPROVAL = "needs_approval"   # destructive — ask Sir first
    BLOCKED = "blocked"          # unconditionally refused


@dataclass
class SafetyVerdict:
    """Result of validating a single command."""

    level: VerdictLevel
    reason: str = ""
    matched_pattern: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.level is VerdictLevel.ALLOWED

    @property
    def needs_approval(self) -> bool:
        return self.level is VerdictLevel.NEEDS_APPROVAL

    @property
    def blocked(self) -> bool:
        return self.level is VerdictLevel.BLOCKED


# Control characters that have no business appearing in a chat-origin command.
# We allow tab (\t) and newline (\n) because legitimate multi-line PowerShell
# and here-strings use them; everything else in 0x00-0x1F plus 0x7F is rejected.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_command(command: str) -> SafetyVerdict:
    """
    Inspect a command and decide whether it may run.

    Args:
        command: Raw command string emitted by the LLM or interpreter.

    Returns:
        SafetyVerdict with level ALLOWED, NEEDS_APPROVAL, or BLOCKED.
    """
    if not command or not command.strip():
        return SafetyVerdict(VerdictLevel.BLOCKED, reason="Empty command")

    # 1. Length cap — defends against prompt-bomb style payloads.
    if len(command) > MAX_COMMAND_LENGTH:
        return SafetyVerdict(
            VerdictLevel.BLOCKED,
            reason=f"Command exceeds maximum length {MAX_COMMAND_LENGTH}",
        )

    # 2. Control-character rejection.
    if _CONTROL_CHARS.search(command):
        return SafetyVerdict(
            VerdictLevel.BLOCKED,
            reason="Command contains forbidden control characters",
        )

    normalized = command.strip()

    # 3. Hard blocklist — never run, never approvable.
    for pattern, reason in BLOCKED_COMMAND_PATTERNS:
        if pattern.search(normalized):
            log.warning("command_blocked", command_preview=normalized[:80], reason=reason)
            return SafetyVerdict(
                VerdictLevel.BLOCKED,
                reason=reason,
                matched_pattern=pattern.pattern,
            )

    # 4. Dangerous — route to approval gateway.
    for pattern, reason in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(normalized):
            log.warning("command_flagged_dangerous", command_preview=normalized[:80], reason=reason)
            return SafetyVerdict(
                VerdictLevel.NEEDS_APPROVAL,
                reason=reason,
                matched_pattern=pattern.pattern,
            )

    # 5. All clear.
    return SafetyVerdict(VerdictLevel.ALLOWED)


# Module-level singleton for convenience
command_safety = command_safety if "command_safety" in globals() else None


def get_validator() -> "CommandSafety":
    """Return the process-wide CommandSafety instance."""
    return CommandSafety()


class CommandSafety:
    """
    Thin OO wrapper around :func:`validate_command` so callers can hold a
    stateful validator if they want to add per-session allow-rules later.
    """

    def validate(self, command: str) -> SafetyVerdict:
        return validate_command(command)


# Shared singleton
command_safety = CommandSafety()
