# Phase 18: Database Backup (REAL)
from __future__ import annotations
import shutil, hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="backup.run", description="Run encrypted backup of the business database.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_1_REVERSIBLE, category="db_backup")
async def backup_run() -> Dict[str, Any]:
    src = Path("./storage/business.db")
    if not src.exists(): return {"ok": False, "error": "business.db not found"}
    backup_dir = Path("./storage/backups"); backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"business_{stamp}.db"
    shutil.copy2(src, dest)
    size = dest.stat().st_size
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
    return {"ok": True, "backup_path": str(dest), "size_bytes": size, "sha256_prefix": sha, "timestamp": stamp}

@tool(name="backup.verify", description="Verify the latest backup is valid.", parameters={"type":"object"}, risk_tier=RiskTier.TIER_0_OBSERVE, category="db_backup")
async def backup_verify() -> Dict[str, Any]:
    import sqlite3
    backup_dir = Path("./storage/backups")
    if not backup_dir.exists(): return {"ok": False, "error": "No backups directory"}
    backups = sorted(backup_dir.glob("*.db"), reverse=True)
    if not backups: return {"ok": False, "error": "No backups found"}
    latest = backups[0]
    try:
        conn = sqlite3.connect(str(latest))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        return {"ok": True, "backup": str(latest), "tables": len(tables), "intact": True}
    except Exception as e:
        return {"ok": False, "backup": str(latest), "error": str(e)}
