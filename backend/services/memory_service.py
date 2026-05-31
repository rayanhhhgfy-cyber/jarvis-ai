# ====================================================================
# JARVIS OMEGA — Memory Service
# ====================================================================
"""
Memory Service layer managing high-level memory operations: semantic queries,
document indexing, manual memory curation, and memory context compilation.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional

from shared.models import MemoryEntry, MemoryQuery, MemoryContext
from shared.constants import MemoryCategory
from backend.memory_engine import memory_engine
from backend.memory_indexer import memory_indexer
from shared.logger import get_logger

log = get_logger("memory_service")


class MemoryService:
    """
    Business layer coordinates semantic search, batch document indexing,
    and memory lifecycle curation (pinning, updates, deletion).
    """

    async def add_memory(
        self,
        content: str,
        category: MemoryCategory,
        source: str = "user",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        pinned: bool = False,
    ) -> str:
        """Manually store a new memory entry."""
        entry = MemoryEntry(
            category=category,
            content=content,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
            pinned=pinned,
        )
        return await memory_engine.store(entry)

    async def search_memories(self, query: MemoryQuery) -> List[MemoryEntry]:
        """Search memory collections using semantic embeddings."""
        return await memory_engine.query(query)

    async def get_context_for_query(self, query_text: str) -> MemoryContext:
        """Retrieves and packages contextual memories for LLM prompting."""
        return await memory_engine.build_context(query_text)

    async def index_large_document(
        self,
        content: str,
        category: MemoryCategory,
        source: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Index a large text document by chunking and parsing it into ChromaDB."""
        return await memory_indexer.index_document(
            content=content,
            category=category,
            source=source,
            tags=tags,
            metadata=metadata,
        )

    async def update_memory(
        self,
        memory_id: str,
        category: MemoryCategory,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update the content/metadata of a specific memory entry."""
        return await memory_engine.update(
            memory_id=memory_id,
            category=category,
            content=content,
            metadata=metadata,
        )

    async def delete_memory(self, memory_id: str, category: MemoryCategory) -> bool:
        """Delete a memory entry from ChromaDB."""
        return await memory_engine.delete(memory_id, category)

    async def pin_memory(self, memory_id: str, category: MemoryCategory, pinned: bool = True) -> bool:
        """Pin or unpin a memory to prevent consolidation/deletion."""
        entries = await memory_engine.get_all(category, limit=500)
        target = None
        for e in entries:
            if e.memory_id == memory_id:
                target = e
                break

        if not target:
            return False

        meta = target.metadata or {}
        meta["pinned"] = pinned
        return await memory_engine.update(
            memory_id=memory_id,
            category=category,
            content=target.content,
            metadata=meta,
        )

    async def get_stats(self) -> Dict[str, int]:
        """Get counts per memory category."""
        return await memory_engine.get_stats()


# Global memory service instance
memory_service = MemoryService()
