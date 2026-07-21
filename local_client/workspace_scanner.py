# ====================================================================
# JARVIS OMEGA — Local Workspace Scanner
# ====================================================================
"""
Scans and aggregates folder structures and file sizes locally.
Constructs directory hierarchies and maps paths for project uploads.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Any

from shared.logger import get_logger

log = get_logger("workspace_scanner")


class WorkspaceScanner:
    """
    Scans files locally in workspace folder and builds file hierarchy indexes.
    """

    def __init__(self, workspace_path: str = "./workspace") -> None:
        self.workspace_path = Path(workspace_path)

    def scan_structure(self) -> Dict[str, Any]:
        """
        Builds a quick JSON-serializable directory tree hierarchy
        and listing of files with their metadata.
        """
        log.info("scanning_local_workspace_structure", path=str(self.workspace_path))
        if not self.workspace_path.exists():
            self.workspace_path.mkdir(parents=True, exist_ok=True)

        return self._scan_node(self.workspace_path)

    def _scan_node(self, path: Path) -> Dict[str, Any]:
        """Recursive helper to map files and folders."""
        name = path.name or "workspace"
        rel_path = path.relative_to(self.workspace_path)

        if path.is_dir():
            children = []
            try:
                for entry in path.iterdir():
                    # Skip hidden items and environments
                    if entry.name.startswith(".") or entry.name in ("node_modules", "venv", "__pycache__"):
                        continue
                    children.append(self._scan_node(entry))
            except PermissionError:
                log.warning("permission_denied_scanning_node", path=str(path))
            
            return {
                "name": name,
                "type": "folder",
                "path": str(rel_path.as_posix()),
                "children": children,
            }
        else:
            stat = path.stat()
            return {
                "name": name,
                "type": "file",
                "path": str(rel_path.as_posix()),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            }


# Global workspace scanner instance
workspace_scanner = WorkspaceScanner()
