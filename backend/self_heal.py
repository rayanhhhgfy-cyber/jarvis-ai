# ====================================================================
# JARVIS OMEGA — Self-Healing Supervisor (Phase 9)
# ====================================================================
"""
Watches the running backend for repeated failures and triggers autonomous
repair without Sir's intervention.

Two activation paths:

  1. **Passive (auto_self_heal=True)** — installs ``sys.excepthook`` and an
     ``asyncio`` exception handler. When the same traceback fingerprint fires
     ``SELF_MODIFY_MAX_ATTEMPTS`` times, the supervisor invokes
     ``agent_self_modify`` to diagnose + patch the file.

  2. **Active (explicit invoke)** — chat router / orchestrator call
     ``self_heal.try_heal(...)`` when a tool call fails repeatedly.

Every patch is:
  - Backed up to ``SELF_MODIFY_BACKUP_DIR`` (full original file)
  - Validated by re-running ``pytest backend/tests/`` (must not regress)
  - Audit-logged as JSON in ``SELF_MODIFY_AUDIT_DIR``
  - Refused outright if it touches a path in ``SELF_MODIFY_PROTECTED_PATHS``

If ``settings.allow_self_modification`` is False, the supervisor still
diagnoses and proposes patches, but it routes them through the approval
gateway instead of applying them.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from shared.constants import (
    SELF_MODIFY_ALLOWED_GLOBS,
    SELF_MODIFY_AUDIT_DIR,
    SELF_MODIFY_BACKUP_DIR,
    SELF_MODIFY_PROTECTED_PATHS,
)
from shared.logger import get_logger
from shared.security import sha256_hash as sha256_str

from backend.config import settings

log = get_logger("self_heal")


# --------------------------------------------------------------------
# Path policy
# --------------------------------------------------------------------

def _norm(p: str | Path) -> str:
    return str(p).replace("\\", "/").lstrip("./")


def is_protected(path: str | Path) -> bool:
    n = _norm(path)
    for p in SELF_MODIFY_PROTECTED_PATHS:
        if n == _norm(p) or n.endswith("/" + _norm(p)):
            return True
    return False


def is_allowed(path: str | Path) -> bool:
    n = _norm(path)
    if is_protected(n):
        return False
    for pattern in SELF_MODIFY_ALLOWED_GLOBS:
        # Normalize the pattern the same way as the path.
        pat = _norm(pattern)
        # ``fnmatch`` treats ``**`` identically to ``*`` — collapse ``**/``
        # so both ``backend/main.py`` and ``backend/a/b.py`` match
        # ``backend/**/*.py``.
        if "**/" in pat:
            # Convert ``backend/**/*.py`` -> match against ``backend/*.py``
            # AND ``backend/*/*.py`` (recursively via fnmatch's ``*``).
            top = pat.replace("**/", "")
            deep = pat.replace("**/", "*/")
            verydeep = pat.replace("**/", "*/*/")
            if fnmatch.fnmatch(n, top) or fnmatch.fnmatch(n, deep) or fnmatch.fnmatch(n, verydeep):
                return True
        elif fnmatch.fnmatch(n, pat):
            return True
    return False


# --------------------------------------------------------------------
# Backup + audit
# --------------------------------------------------------------------

def _backup_original(path: str | Path) -> Optional[str]:
    """Copy ``path`` to the backup dir, return the backup path or None on failure."""
    src = Path(path)
    if not src.is_file():
        return None
    backup_dir = Path(SELF_MODIFY_BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_name = _norm(path).replace("/", "__")
    dest = backup_dir / f"{stamp}__{safe_name}"
    try:
        shutil.copy2(src, dest)
        return str(dest)
    except Exception as e:
        log.warning("self_modify_backup_failed", path=path, error=str(e))
        return None


def _write_audit(record: Dict[str, Any]) -> None:
    audit_dir = Path(SELF_MODIFY_AUDIT_DIR)
    audit_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    fingerprint = sha256_str(record.get("traceback", "") + record.get("target_path", ""))[:8]
    dest = audit_dir / f"{stamp}__{fingerprint}.json"
    try:
        dest.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning("self_modify_audit_write_failed", error=str(e))


# --------------------------------------------------------------------
# Fingerprint memory — so we don't try to fix the same crash forever
# --------------------------------------------------------------------

class _FailureMemory:
    """Tracks how often each (file, line, exception) fingerprint has fired."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}
        self._last_attempt: Dict[str, datetime] = {}

    def record(self, fingerprint: str) -> int:
        self._counts[fingerprint] = self._counts.get(fingerprint, 0) + 1
        return self._counts[fingerprint]

    def count(self, fingerprint: str) -> int:
        return self._counts.get(fingerprint, 0)

    def mark_attempted(self, fingerprint: str) -> None:
        self._last_attempt[fingerprint] = datetime.utcnow()

    def recently_attempted(self, fingerprint: str, within_seconds: int = 60) -> bool:
        last = self._last_attempt.get(fingerprint)
        if not last:
            return False
        return (datetime.utcnow() - last).total_seconds() < within_seconds


_memory = _FailureMemory()


def _fingerprint(traceback_str: str) -> str:
    """Stable hash of a traceback (ignoring variable values, which vary)."""
    # Keep only "File ... line N" lines so the fingerprint is stable across
    # different argument values in the same code path.
    stable_lines = [
        line for line in traceback_str.splitlines()
        if line.strip().startswith('File "')
    ]
    return sha256_str("\n".join(stable_lines))[:16]


# --------------------------------------------------------------------
# Repair invocation
# --------------------------------------------------------------------

async def try_heal(
    *,
    error: Optional[BaseException] = None,
    traceback_str: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    requesting_agent: str = "supervisor",
) -> Dict[str, Any]:
    """
    Diagnose an error and (if allowed) patch the offending file.

    Returns a structured record describing what was attempted.
    """
    tb = traceback_str or (traceback.format_exc() if error else "")
    if not tb or tb == "NoneType: None\n":
        return {"healed": False, "reason": "no traceback available"}

    fingerprint = _fingerprint(tb)
    _memory.record(fingerprint)
    if _memory.recently_attempted(fingerprint, within_seconds=60):
        return {
            "healed": False,
            "reason": "repair already attempted for this fingerprint in the last 60s",
            "fingerprint": fingerprint,
        }

    _memory.mark_attempted(fingerprint)

    # Diagnose.
    from local_client.agents.agent_self_modify import AgentSelfModify
    from shared.constants import AgentType
    from shared.models import TaskDefinition

    task = TaskDefinition(
        title="auto-heal",
        description="Auto-repair an exception caught by the supervisor.",
        agent_type=AgentType.SELF_MODIFY,
        payload={
            "action": "fix_self",
            "traceback": tb,
            "context": context or {},
            "allow_self_modification": settings.allow_self_modification,
            "requesting_agent": requesting_agent,
        },
    )

    log.warning("self_heal_triggered", fingerprint=fingerprint, requesting_agent=requesting_agent)

    try:
        result = await AgentSelfModify().execute_task(task)
        record: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "fingerprint": fingerprint,
            "requesting_agent": requesting_agent,
            "traceback": tb,
            "context": context or {},
            "result": result.model_dump(mode="json"),
        }
        _write_audit(record)
        return record
    except Exception as heal_err:
        log.error("self_heal_failed", error=str(heal_err), exc_info=True)
        return {
            "healed": False,
            "reason": f"heal pipeline raised: {heal_err}",
            "fingerprint": fingerprint,
        }


# --------------------------------------------------------------------
# Process-level hooks
# --------------------------------------------------------------------

_original_excepthook = sys.excepthook
_original_asyncio_handler: Optional[Callable] = None


def _sync_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Custom sys.excepthook that fires the heal pipeline on repeated crashes."""
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        log.error("unhandled_exception", traceback=tb_str)
    except Exception:
        pass

    fingerprint = _fingerprint(tb_str)
    seen = _memory.record(fingerprint)
    # Only auto-heal after the same crash fires 2+ times — once might be a fluke.
    if settings.auto_self_heal and seen >= 2 and not _memory.recently_attempted(fingerprint, 60):
        log.warning("auto_heal_threshold_reached", fingerprint=fingerprint, count=seen)
        try:
            asyncio.get_event_loop().create_task(
                try_heal(error=exc_value, traceback_str=tb_str,
                         context={"source": "sys.excepthook", "count": seen})
            )
        except Exception as fire_err:
            log.warning("auto_heal_dispatch_failed", error=str(fire_err))

    # Always call the original hook so the crash is visible in stderr too.
    _original_excepthook(exc_type, exc_value, exc_tb)


def _asyncio_exception_handler(loop, context) -> None:
    """Custom asyncio exception handler."""
    exc: Optional[BaseException] = context.get("exception")
    tb_str = ""
    if exc:
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        log.error("unhandled_async_exception", message=context.get("message"), traceback=tb_str)
    except Exception:
        pass

    fingerprint = _fingerprint(tb_str) if tb_str else "no-tb"
    seen = _memory.record(fingerprint)
    if settings.auto_self_heal and seen >= 2 and not _memory.recently_attempted(fingerprint, 60):
        loop.create_task(
            try_heal(error=exc, traceback_str=tb_str,
                     context={"source": "asyncio", "message": context.get("message"), "count": seen})
        )

    # Call the original handler if present.
    if _original_asyncio_handler:
        _original_asyncio_handler(loop, context)


def install() -> None:
    """Install the self-heal excepthook + asyncio handler. Idempotent."""
    global _original_asyncio_handler
    if sys.excepthook is not _sync_excepthook:
        sys.excepthook = _sync_excepthook
    try:
        loop = asyncio.get_event_loop()
        if _original_asyncio_handler is None:
            _original_asyncio_handler = loop.get_exception_handler()
        loop.set_exception_handler(_asyncio_exception_handler)
    except RuntimeError:
        # No running loop yet — that's fine; we'll catch up on first async exception.
        pass
    log.info("self_heal_installed", auto_self_heal=settings.auto_self_heal)


# --------------------------------------------------------------------
# Test-gate — verifies a patch doesn't regress
# --------------------------------------------------------------------

async def run_test_gate(test_path: str = "backend/tests/", timeout: int = 120) -> Dict[str, Any]:
    """Run pytest after a patch and return parsed result. Returns ok=False on regression."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", test_path, "-x", "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return {"ok": False, "error": f"pytest timed out after {timeout}s"}
    rc = proc.returncode or 0
    return {
        "ok": rc == 0,
        "exit_code": rc,
        "stdout_tail": out.decode("utf-8", errors="replace")[-2000:],
        "stderr_tail": err.decode("utf-8", errors="replace")[-2000:],
    }
