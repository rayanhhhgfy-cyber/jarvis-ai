# ====================================================================
# JARVIS OMEGA - Backup Plugin (wraps the existing backup_manager)
# ====================================================================
"""
Phase 10 plugin: surface the existing (previously un-wired)
``backend.backup_manager.BackupManager`` as callable tools.

  * ``backup.run_now``    - create a zip backup immediately
  * ``backup.list``       - list existing backup archives
  * ``backup.schedule``   - register a periodic backup job via APScheduler
  * ``backup.verify``     - compute SHA-256 of an archive (integrity check)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

from backend.tools import tool, RiskTier


def _manager():
    """Lazy import so plugin import never fails if backend changes."""
    from backend.backup_manager import backup_manager
    return backup_manager


@tool(
    name="backup.run_now",
    description="Create a ZIP backup of configs/shared/backend code now. Returns BackupInfo.",
    parameters={
        "type": "object",
        "properties": {
            "backup_type": {
                "type": "string",
                "enum": ["all", "configs", "shared", "backend"],
                "default": "all",
            },
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="backup",
)
async def backup_run_now(backup_type: str = "all") -> Dict[str, Any]:
    try:
        info = await _manager().create_backup(backup_type=backup_type)
        return info.model_dump(mode="json")
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="backup.list",
    description="List existing backup ZIP archives.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="backup",
)
async def backup_list() -> Dict[str, Any]:
    try:
        backups = await _manager().list_backups()
        return {"ok": True, "count": len(backups), "backups": backups}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="backup.schedule",
    description="Register a recurring backup job with APScheduler. Returns the job_id.",
    parameters={
        "type": "object",
        "properties": {
            "interval_minutes": {"type": "integer", "default": 60},
            "backup_type": {"type": "string", "enum": ["all", "configs", "shared", "backend"], "default": "all"},
            "job_id": {"type": "string", "default": "auto-backup"},
        },
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="backup",
)
async def backup_schedule(
    interval_minutes: int = 60, backup_type: str = "all", job_id: str = "auto-backup",
) -> Dict[str, Any]:
    try:
        from backend.scheduler import scheduler

        async def _job():
            try:
                await _manager().create_backup(backup_type=backup_type)
            except Exception as e:
                # Log via the existing logger inside manager.
                pass

        jid = scheduler.schedule_interval(
            job_id=job_id,
            func=_job,
            minutes=interval_minutes,
            description=f"Auto {backup_type} backup every {interval_minutes}m",
        )
        return {"ok": True, "job_id": jid, "interval_minutes": interval_minutes, "backup_type": backup_type}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool(
    name="backup.verify",
    description="Verify the integrity of a backup archive by recomputing its SHA-256.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the .zip archive."},
            "expected_sha256": {"type": "string", "default": "", "description": "Optional checksum to compare against."},
        },
        "required": ["path"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="backup",
)
async def backup_verify(path: str, expected_sha256: str = "") -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    try:
        sha = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                sha.update(chunk)
        digest = sha.hexdigest()
        match = (not expected_sha256) or (digest == expected_sha256)
        return {
            "ok": True,
            "path": path,
            "size_bytes": p.stat().st_size,
            "sha256": digest,
            "matches_expected": match if expected_sha256 else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


PLUGIN_NAME = "backup_local"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Wraps the existing BackupManager as callable tools. Run, list, schedule, verify."
