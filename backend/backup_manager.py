# ====================================================================
# JARVIS OMEGA — Backup Manager
# ====================================================================
"""
Automated backup manager. Compresses and packages workspace memory databases,
ChromaDB vectors, configurations, and logs with checksum integrity validation.
"""

from __future__ import annotations

import os
import time
import zipfile
import hashlib
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import BackupInfo
from shared.logger import get_logger

log = get_logger("backup_manager")

class BackupManager:
    """
    Automated backup scheduler core. Packages system databases, saves vector states,
    creates release configurations, and handles backup retention rotations.
    """

    def __init__(self, backup_dir: str = "./backups") -> None:
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    async def create_backup(self, backup_type: str = "all") -> BackupInfo:
        """
        Creates a zip archive of system files depending on backup type requested.
        Generates SHA-256 integrity checksums.
        """
        log.info("creating_system_backup", type=backup_type)
        start_time = time.time()
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"jarvis_backup_{backup_type}_{timestamp}.zip"
        archive_path = os.path.join(self.backup_dir, filename)

        try:
            # Files to bundle based on type
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                if backup_type in ["configs", "all"]:
                    # Bundle env, package details
                    if os.path.exists(".env"):
                        zipf.write(".env")
                    if os.path.exists("requirements.txt"):
                        zipf.write("requirements.txt")

                if backup_type in ["shared", "all"]:
                    # Bundle shared packages
                    self._zip_directory("shared", zipf)

                if backup_type in ["backend", "all"]:
                    # Bundle backend logic
                    self._zip_directory("backend", zipf)

            # Compute SHA-256 checksum
            sha256 = hashlib.sha256()
            with open(archive_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256.update(chunk)
            checksum = sha256.hexdigest()

            size = os.path.getsize(archive_path)
            
            info = BackupInfo(
                backup_type=backup_type,
                path=os.path.abspath(archive_path),
                size_bytes=size,
                checksum=checksum
            )

            log.info("backup_created_successfully", path=info.path, size=size, checksum=checksum)
            return info

        except Exception as e:
            if os.path.exists(archive_path):
                os.remove(archive_path)
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("backup_generation_failed", error=err_msg)
            raise RuntimeError(f"Failed to create system backup: {str(e)}")

    def _zip_directory(self, folder_path: str, zip_file: zipfile.ZipFile) -> None:
        """Helper to recursively zip target directories."""
        if not os.path.exists(folder_path):
            return
        for root, _, files in os.walk(folder_path):
            for file in files:
                if "__pycache__" in root or ".git" in root:
                    continue
                file_path = os.path.join(root, file)
                # Compute relative path inside zip
                arcname = os.path.relpath(file_path, os.path.dirname(folder_path))
                zip_file.write(file_path, arcname)

    async def list_backups(self) -> List[Dict[str, Any]]:
        """Retrieves list of existing compressed archives in folder."""
        backups = []
        if not os.path.exists(self.backup_dir):
            return []
            
        for file in os.listdir(self.backup_dir):
            if file.startswith("jarvis_backup_") and file.endswith(".zip"):
                path = os.path.join(self.backup_dir, file)
                stat = os.stat(path)
                backups.append({
                    "filename": file,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "path": os.path.abspath(path)
                })
        return backups

# Global instance
backup_manager = BackupManager()
