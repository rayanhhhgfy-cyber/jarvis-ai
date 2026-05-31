# ====================================================================
# JARVIS OMEGA — Structured Logging
# ====================================================================
"""
Structured logging with audit trail support, log rotation,
categorized outputs, and both console and file handlers.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

# ---- Module State ----
_initialized = False
_log_dir: Optional[Path] = None


def setup_logging(
    log_dir: str = "./logs",
    log_level: str = "INFO",
    log_format: str = "json",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Initialize the structured logging system."""
    global _initialized, _log_dir

    if _initialized:
        return

    _log_dir = Path(log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)

    # Sub-directories for categorized logs
    for subdir in ["agents", "tasks", "security", "audit", "system", "errors"]:
        (_log_dir / subdir).mkdir(exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Standard library logging for file output
    root_logger = logging.getLogger("jarvis_omega")
    root_logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # Main file handler with rotation
    main_handler = RotatingFileHandler(
        _log_dir / "jarvis_omega.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    main_handler.setLevel(level)
    main_handler.setFormatter(console_fmt)
    root_logger.addHandler(main_handler)

    # Error file handler
    error_handler = RotatingFileHandler(
        _log_dir / "errors" / "errors.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(console_fmt)
    root_logger.addHandler(error_handler)

    _initialized = True


def get_logger(name: str = "jarvis_omega") -> structlog.BoundLogger:
    """Get a structured logger instance."""
    if not _initialized:
        setup_logging()
    return structlog.get_logger(name)


def get_std_logger(name: str = "jarvis_omega") -> logging.Logger:
    """Get a standard library logger instance."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)


# ====================================================================
# AUDIT LOGGER
# ====================================================================

class AuditLogger:
    """
    Dedicated audit logger that writes immutable audit entries
    to a separate audit log file. Every critical action is recorded.
    """

    def __init__(self, log_dir: str = "./logs"):
        self._log_dir = Path(log_dir) / "audit"
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger("jarvis_omega.audit")
        self._logger.setLevel(logging.INFO)

        if not self._logger.handlers:
            handler = RotatingFileHandler(
                self._log_dir / "audit.log",
                maxBytes=50 * 1024 * 1024,  # 50MB
                backupCount=10,
                encoding="utf-8",
            )
            fmt = logging.Formatter("%(message)s")
            handler.setFormatter(fmt)
            self._logger.addHandler(handler)

        self._struct_log = get_logger("audit")

    def log(
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
        """Record an audit log entry."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "category": category,
            "action": action,
            "status": status,
            "device_id": device_id,
            "user": user,
            "agent": agent,
            "details": details or {},
            "execution_duration_ms": execution_duration_ms,
        }

        import json
        self._logger.info(json.dumps(entry))

        self._struct_log.info(
            "audit_event",
            category=category,
            action=action,
            status=status,
            agent=agent,
        )

        return entry


# ====================================================================
# AGENT LOGGER
# ====================================================================

class AgentLogger:
    """Logger specialized for agent activity tracking."""

    def __init__(self, agent_type: str, agent_id: str):
        self._log = get_logger(f"agent.{agent_type}")
        self._agent_type = agent_type
        self._agent_id = agent_id

    def task_started(self, task_id: str, description: str) -> None:
        self._log.info(
            "task_started",
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            task_id=task_id,
            description=description,
        )

    def task_completed(self, task_id: str, duration_ms: float) -> None:
        self._log.info(
            "task_completed",
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            task_id=task_id,
            duration_ms=duration_ms,
        )

    def task_failed(self, task_id: str, error: str) -> None:
        self._log.error(
            "task_failed",
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            task_id=task_id,
            error=error,
        )

    def info(self, message: str, **kwargs: Any) -> None:
        self._log.info(message, agent_id=self._agent_id, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log.warning(message, agent_id=self._agent_id, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log.error(message, agent_id=self._agent_id, **kwargs)
