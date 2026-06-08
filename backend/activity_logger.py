# ====================================================================
# JARVIS OMEGA — Activity & Audit Logger Service
# ====================================================================
"""
Service wrapper around structured audit logs. Provides query, filtering,
aggregation, and inspection capabilities over system events.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from shared.logger import get_logger, AuditLogger
from shared.models import AuditLogEntry
from backend.config import settings

log = get_logger("activity_logger")


class ActivityLogger:
    """
    Manages querying, streaming, and filtering of audit log records.
    Wraps log file parsing and structured audit output.
    """

    def __init__(self, logs_dir: str = "./logs") -> None:
        self._audit_log_path = Path(logs_dir) / "audit" / "audit.log"
        self._raw_logger = AuditLogger(log_dir=logs_dir)

    def log_action(
        self,
        category: str,
        action: str,
        status: str = "success",
        device_id: str = "",
        user: str = "Sir",
        agent: str = "",
        details: Optional[Dict[str, Any]] = None,
        execution_duration_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Submit a new record to the immutable audit log file."""
        return self._raw_logger.log(
            category=category,
            action=action,
            status=status,
            device_id=device_id,
            user=user,
            agent=agent,
            details=details,
            execution_duration_ms=execution_duration_ms,
        )

    def query_logs(
        self,
        category: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        device_id: Optional[str] = None,
        agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditLogEntry]:
        """
        Parses and filters logs from the audit log file.
        Returns a list of parsed AuditLogEntry objects.
        """
        results: List[AuditLogEntry] = []
        if not self._audit_log_path.exists():
            return results

        try:
            # Read lines in reverse order to get newest entries first
            with open(self._audit_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry_dict = json.loads(line)
                    
                    # Apply filters
                    if category and entry_dict.get("category") != category:
                        continue
                    if action and entry_dict.get("action") != action:
                        continue
                    if status and entry_dict.get("status") != status:
                        continue
                    if device_id and entry_dict.get("device_id") != device_id:
                        continue
                    if agent and entry_dict.get("agent") != agent:
                        continue

                    results.append(AuditLogEntry(
                        category=entry_dict.get("category", "general"),
                        action=entry_dict.get("action", "unknown"),
                        status=entry_dict.get("status", "success"),
                        device_id=entry_dict.get("device_id", ""),
                        user=entry_dict.get("user", "Sir"),
                        agent=entry_dict.get("agent", ""),
                        details=entry_dict.get("details", {}),
                        execution_duration_ms=entry_dict.get("execution_duration_ms", 0.0),
                        timestamp=datetime.fromisoformat(entry_dict.get("timestamp")),
                    ))

                    if len(results) >= limit:
                        break
                except Exception as line_err:
                    log.error("audit_line_parse_error", error=str(line_err))
        except Exception as file_err:
            log.error("audit_file_read_error", error=str(file_err))

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Retrieve aggregated event counts by category and status."""
        stats: Dict[str, Any] = {
            "total_events": 0,
            "by_category": {},
            "by_status": {},
        }

        if not self._audit_log_path.exists():
            return stats

        try:
            with open(self._audit_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        stats["total_events"] += 1

                        cat = entry.get("category", "unknown")
                        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

                        status_val = entry.get("status", "unknown")
                        stats["by_status"][status_val] = stats["by_status"].get(status_val, 0) + 1
                    except Exception:
                        pass
        except Exception as e:
            log.error("stats_generation_failed", error=str(e))

        return stats


# Global activity logger service
activity_logger = ActivityLogger(logs_dir=settings.logs_dir)
