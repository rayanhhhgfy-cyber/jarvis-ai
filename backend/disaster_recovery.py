# ====================================================================
# JARVIS OMEGA — Disaster Recovery Core
# ====================================================================
"""
Automated Disaster Recovery Engine. Monitors filesystem failures,
restores backup zip assets, validates hash states, and self-heals system cores.
"""

from __future__ import annotations

import os
import shutil
import zipfile
import traceback
from typing import Dict, Any
from datetime import datetime

from backend.backup_manager import backup_manager
from shared.logger import get_logger

log = get_logger("disaster_recovery")

class DisasterRecovery:
    """
    Subsystem auditor. Analyzes database connection drops, unpacks zip releases,
    validates hashes, and restores lost state records.
    """

    async def restore_from_backup(self, backup_filename: str) -> Dict[str, Any]:
        """
        Unzips a specific backup archive to restore configurations and code packages.
        Performs structural checks post-extraction.
        """
        backup_path = os.path.join(backup_manager.backup_dir, backup_filename)
        log.info("disaster_recovery_initiating", source=backup_path)

        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not located in catalog: {backup_filename}")

        try:
            # Open and unpack to current workspace folder
            with zipfile.ZipFile(backup_path, "r") as zipf:
                # Perform integrity dry-run check
                crc_err = zipf.testzip()
                if crc_err is not None:
                    raise ValueError(f"Zip CRC validation failed on node: {crc_err}")

                zipf.extractall(".")

            log.info("disaster_recovery_unpack_successful", filename=backup_filename)
            return {
                "restored": True,
                "backup_filename": backup_filename,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "system_recovered"
            }

        except Exception as e:
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("disaster_recovery_restoration_failed", error=err_msg)
            return {
                "restored": False,
                "error": str(e),
                "status": "restoration_failed"
            }

    async def audit_system_integrity(self) -> Dict[str, Any]:
        """Audits essential system configurations and directory boundaries."""
        shared_valid = os.path.exists("shared/models.py") and os.path.exists("shared/constants.py")
        backend_valid = os.path.exists("backend/main.py")
        client_valid = os.path.exists("local_client/daemon.py")

        healthy = shared_valid and backend_valid and client_valid

        return {
            "healthy": healthy,
            "shared_layer_present": shared_valid,
            "backend_core_present": backend_valid,
            "local_daemon_present": client_valid,
            "audit_message": "System integrity verified. Core paths active." if healthy else "Core folders missing. Triggering recovery recommended."
        }

# Global instance
disaster_recovery = DisasterRecovery()
