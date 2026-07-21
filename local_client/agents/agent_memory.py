# ====================================================================
# JARVIS OMEGA — Memory Agent
# ====================================================================
"""
Specialized Memory Agent responsible for vector memory optimization,
tag categorization, duplicate filtering, and database synchronization.

Phase 4: real ChromaDB-backed archival of low-relevance/old entries +
pruning of empty log files. No more hardcoded "12 pruned" numbers.
"""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from shared.models import TaskDefinition, TaskResult, MemoryEntry
from shared.constants import AgentType, TaskStatus, MemoryCategory
from shared.logger import get_logger

log = get_logger("agent_memory")


# Categories elegible for archival (excludes long-lived ones like PREFERENCES).
_ARCHIVABLE_CATEGORIES = (
    MemoryCategory.CONVERSATIONS,
    MemoryCategory.TASKS,
    MemoryCategory.DEBUGGING,
    MemoryCategory.RESEARCH,
)


class AgentMemory:
    """
    Memory Optimization and clean agent. Works with ChromaDB database vectors
    to cluster matching profiles, deduplicate logs, and index files.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_memory"
        self.agent_type = AgentType.MEMORY

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes memory operations like index validation or metadata cleaning."""
        log.info("memory_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "optimize")

            if action in ("optimize", "cleanup"):
                result_data = await self._run_memory_cleanup(task)
            elif action == "dedup":
                result_data = await self._deduplicate_entries(task)
            elif action == "prune_logs":
                result_data = await self._prune_empty_logs(task)
            elif action == "stats":
                result_data = await self._gather_stats()
            else:
                raise ValueError(f"Unknown Memory action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("memory_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    # ------------------------------------------------------------------
    # ChromaDB access (lazy import to keep agent importable without ChromaDB)
    # ------------------------------------------------------------------

    def _get_engine(self):
        """Return the shared memory_engine singleton."""
        try:
            from backend.memory_engine import memory_engine
            return memory_engine
        except Exception as e:
            raise RuntimeError(f"memory_engine unavailable: {e}") from e

    # ------------------------------------------------------------------
    # Cleanup / archive
    # ------------------------------------------------------------------

    async def _run_memory_cleanup(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Archive low-relevance / stale entries from every archival category.

        Entries whose ``relevance_score`` is below ``min_relevance`` (default
        0.15) OR whose ``created_at`` is older than ``max_age_days`` (default
        60) are deleted from the live collection. Pinned entries are never
        archived.

        Returns counts per category plus a total.
        """
        engine = self._get_engine()
        min_relevance = float(task.payload.get("min_relevance", 0.15))
        max_age_days = int(task.payload.get("max_age_days", 60))
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        dry_run = bool(task.payload.get("dry_run", False))

        per_category: Dict[str, int] = {}
        total_archived = 0
        total_inspected = 0
        errors: List[str] = []

        for category in _ARCHIVABLE_CATEGORIES:
            archived_for_category = 0
            try:
                entries: List[MemoryEntry] = await engine.get_all(category, limit=10000)
                total_inspected += len(entries)
                for entry in entries:
                    if entry.pinned:
                        continue
                    is_low_relevance = entry.relevance_score < min_relevance
                    is_stale = False
                    if entry.created_at:
                        try:
                            is_stale = entry.created_at < cutoff
                        except Exception:
                            is_stale = False

                    if not (is_low_relevance or is_stale):
                        continue

                    if not dry_run:
                        ok = await engine.delete(entry.memory_id, category)
                        if not ok:
                            errors.append(f"failed to archive {entry.memory_id} in {category.value}")
                            continue
                    archived_for_category += 1
            except Exception as cat_err:
                errors.append(f"{category.value}: {cat_err}")

            per_category[category.value] = archived_for_category
            total_archived += archived_for_category

        log.info(
            "memory_cleanup_complete",
            inspected=total_inspected,
            archived=total_archived,
            dry_run=dry_run,
        )

        return {
            "status": "memory_optimization_completed",
            "archived_entries": total_archived,
            "inspected_entries": total_inspected,
            "per_category": per_category,
            "min_relevance_threshold": min_relevance,
            "max_age_days": max_age_days,
            "dry_run": dry_run,
            "errors": errors[:20],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    async def _deduplicate_entries(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Scans a category (or arbitrary ``entries`` list) for near-identical
        content hashes. Optionally deletes duplicates in-place.

        Uses SHA-256 of the normalized content (case-folded, whitespace
        collapsed) — a strict string-equality dedup, not semantic similarity.
        """
        import hashlib

        category_name = task.payload.get("category")
        entries_payload = task.payload.get("entries", [])
        delete_duplicates = bool(task.payload.get("delete", False))

        # Two modes: explicit list (caller supplied) or pull from engine.
        if entries_payload:
            entries = entries_payload
            category: Optional[MemoryCategory] = None
        elif category_name:
            try:
                category = MemoryCategory(category_name)
            except ValueError as e:
                raise ValueError(f"unknown category: {category_name}") from e
            engine = self._get_engine()
            entries = [
                e.model_dump() for e in await engine.get_all(category, limit=10000)
            ]
        else:
            raise ValueError("dedup requires either 'entries' or 'category' in payload")

        seen_hashes: Dict[str, str] = {}  # hash -> first memory_id
        unique_entries: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []

        for entry in entries:
            content = (entry.get("content") or "").strip().lower()
            content = " ".join(content.split())  # collapse whitespace
            if not content:
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

            memory_id = entry.get("memory_id") or entry.get("id") or ""
            if digest in seen_hashes:
                duplicates.append({
                    "memory_id": memory_id,
                    "original_id": seen_hashes[digest],
                    "preview": (entry.get("content") or "")[:80],
                })
                if delete_duplicates and category is not None and memory_id:
                    try:
                        engine = self._get_engine()
                        await engine.delete(memory_id, category)
                    except Exception as del_err:
                        log.warning("dedup_delete_failed", memory_id=memory_id, error=str(del_err))
            else:
                seen_hashes[digest] = memory_id
                unique_entries.append(entry)

        return {
            "original_count": len(entries),
            "deduplicated_count": len(unique_entries),
            "removed_duplicates": len(duplicates),
            "duplicates": duplicates[:50],
            "delete_applied": delete_duplicates,
        }

    # ------------------------------------------------------------------
    # Empty log pruning
    # ------------------------------------------------------------------

    async def _prune_empty_logs(self, task: TaskDefinition) -> Dict[str, Any]:
        """
        Walks the configured log directory and deletes zero-byte ``*.log``
        files. Useful because the scheduler + health_monitor frequently create
        log files that end up empty after rotation.

        Returns the list of pruned paths.
        """
        from backend.config import settings

        logs_dir = Path(task.payload.get("logs_dir", settings.logs_dir))
        if not logs_dir.exists():
            return {
                "status": "nothing_to_prune",
                "logs_dir": str(logs_dir),
                "pruned": [],
                "pruned_count": 0,
            }

        pruned: List[str] = []
        for path in logs_dir.rglob("*.log"):
            try:
                if path.is_file() and path.stat().st_size == 0:
                    path.unlink(missing_ok=True)
                    pruned.append(str(path))
            except Exception as prune_err:
                log.warning("log_prune_failed", path=str(path), error=str(prune_err))

        return {
            "status": "prune_completed",
            "logs_dir": str(logs_dir),
            "pruned": pruned[:200],
            "pruned_count": len(pruned),
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def _gather_stats(self) -> Dict[str, Any]:
        """Return per-collection counts and total bytes on disk."""
        from backend.config import settings

        engine = self._get_engine()
        try:
            counts = await engine.get_stats()
        except Exception as stat_err:
            counts = {}
            log.warning("memory_stats_unavailable", error=str(stat_err))

        chroma_dir = Path(settings.chroma_persist_dir)
        total_bytes = 0
        if chroma_dir.exists():
            for fp in chroma_dir.rglob("*"):
                if fp.is_file():
                    try:
                        total_bytes += fp.stat().st_size
                    except OSError:
                        pass

        return {
            "per_collection": counts,
            "total_entries": sum(counts.values()) if counts else 0,
            "persist_dir": str(chroma_dir),
            "persist_bytes": total_bytes,
            "persist_mb": round(total_bytes / (1024 * 1024), 2),
        }
