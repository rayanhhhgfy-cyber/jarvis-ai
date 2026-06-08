# ====================================================================
# JARVIS OMEGA — Memory Indexer & Optimizer
# ====================================================================
"""
Background memory indexing, document chunking, memory optimization,
deduplication, consolidation, and cleanup tasks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from shared.constants import MemoryCategory
from shared.logger import get_logger
from shared.models import MemoryEntry
from backend.memory_engine import memory_engine

log = get_logger("memory_indexer")


class MemoryIndexer:
    """
    Indexes files/documents and manages consolidation of memories.
    Combines text chunking, deduplication, and optimization.
    """

    def __init__(self) -> None:
        self._running = False
        self._optimization_interval = 3600 * 12  # every 12 hours
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background optimizer task."""
        self._running = True
        self._task = asyncio.create_task(self._optimize_loop())
        log.info("memory_indexer_started")

    async def stop(self) -> None:
        """Stop the background optimizer task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("memory_indexer_stopped")

    def chunk_text(self, text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        """
        Splits text into chunks with overlap for better embedding quality.
        Ensures chunks do not break sentences or words where possible.
        """
        if not text:
            return []

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break

            # Find near boundary
            boundary = text.rfind("\n", start + chunk_size - 100, end)
            if boundary == -1 or boundary < start + chunk_overlap:
                boundary = text.rfind(" ", start + chunk_size - 20, end)

            if boundary != -1 and boundary > start + chunk_overlap:
                end = boundary

            chunks.append(text[start:end].strip())
            start = end - chunk_overlap

        return chunks

    async def index_document(
        self,
        content: str,
        category: MemoryCategory,
        source: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Index a large document by splitting it into chunks,
        generating unique MemoryEntry IDs, and storing them in ChromaDB.
        """
        chunks = self.chunk_text(content)
        tags = tags or []
        metadata = metadata or {}

        memory_ids = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = {
                **metadata,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            entry = MemoryEntry(
                category=category,
                content=chunk,
                source=source,
                tags=tags + [f"chunk_{i}"],
                metadata=chunk_metadata,
            )
            memory_id = await memory_engine.store(entry)
            if memory_id:
                memory_ids.append(memory_id)

        log.info(
            "document_indexed",
            source=source,
            category=category.value,
            chunks=len(chunks),
            total_stored=len(memory_ids),
        )
        return memory_ids

    async def consolidate_memories(self, category: MemoryCategory) -> None:
        """
        Optimizes stored memories. Removes redundancy, merges highly similar items,
        and archives or flags old, unused short-term memories.
        """
        log.info("memory_consolidation_start", category=category.value)
        entries = await memory_engine.get_all(category, limit=500)
        if len(entries) < 10:
            return

        # Simple semantic-based group and deduplication by exact content similarity matches
        seen_hashes = set()
        removed_count = 0

        for entry in entries:
            import hashlib
            content_hash = hashlib.sha256(entry.content.strip().encode()).hexdigest()
            if content_hash in seen_hashes and not entry.pinned:
                # Duplicate, delete it
                await memory_engine.delete(entry.memory_id, entry.category)
                removed_count += 1
            else:
                seen_hashes.add(content_hash)

        if removed_count > 0:
            log.info("memory_consolidation_complete", category=category.value, removed=removed_count)

    async def _optimize_loop(self) -> None:
        """Periodic memory consolidation loop."""
        while self._running:
            try:
                await asyncio.sleep(self._optimization_interval)
                log.info("triggering_scheduled_memory_optimization")
                for category in MemoryCategory:
                    await self.consolidate_memories(category)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("memory_optimization_loop_failed", error=str(e))


# Global memory indexer instance
memory_indexer = MemoryIndexer()
