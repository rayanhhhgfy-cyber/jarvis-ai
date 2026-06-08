"""
Memory Service layer managing high-level memory operations using SQLite-backed
vector storage. Replaces the ChromaDB-based memory service that was disabled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.memory.sqlite_memory import sqlite_memory
from shared.constants import MemoryCategory
from shared.logger import get_logger
from shared.models import MemoryContext, MemoryEntry, MemoryQuery

log = get_logger("memory_service")


class MemoryService:

    async def add_memory(
        self,
        content: str,
        category: MemoryCategory,
        source: str = "user",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        pinned: bool = False,
    ) -> str:
        try:
            return await sqlite_memory.add(content, category, source, tags, metadata, pinned)
        except Exception as e:
            log.error("memory_add_failed", error=str(e))
            return ""

    async def search_memories(self, query: MemoryQuery) -> List[MemoryEntry]:
        try:
            return await sqlite_memory.search(query)
        except Exception as e:
            log.error("memory_search_failed", error=str(e))
            return []

    async def get_context_for_query(self, query_text: str) -> MemoryContext:
        try:
            return await sqlite_memory.get_context_for_query(query_text)
        except Exception as e:
            log.error("memory_context_failed", error=str(e))
            return MemoryContext()

    async def index_large_document(
        self,
        content: str,
        category: MemoryCategory,
        source: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        ids = []
        chunks = [content[i:i + 1000] for i in range(0, len(content), 1000)]
        for chunk in chunks:
            mid = await self.add_memory(chunk, category, source, tags, metadata)
            if mid:
                ids.append(mid)
        return ids

    async def update_memory(
        self,
        memory_id: str,
        category: MemoryCategory,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        try:
            return await sqlite_memory.update(memory_id, category, content, metadata)
        except Exception as e:
            log.error("memory_update_failed", error=str(e))
            return False

    async def delete_memory(self, memory_id: str, category: MemoryCategory) -> bool:
        try:
            return await sqlite_memory.delete(memory_id)
        except Exception as e:
            log.error("memory_delete_failed", error=str(e))
            return False

    async def pin_memory(self, memory_id: str, category: MemoryCategory, pinned: bool = True) -> bool:
        try:
            return await sqlite_memory.pin(memory_id, pinned)
        except Exception as e:
            log.error("memory_pin_failed", error=str(e))
            return False

    async def get_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        try:
            return await sqlite_memory.get(memory_id)
        except Exception as e:
            log.error("memory_get_failed", error=str(e))
            return None

    async def list_memories(
        self,
        category: Optional[MemoryCategory] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MemoryEntry]:
        try:
            return await sqlite_memory.get_all(category, limit, offset)
        except Exception as e:
            log.error("memory_list_failed", error=str(e))
            return []

    async def get_stats(self) -> Dict[str, int]:
        try:
            return await sqlite_memory.get_stats()
        except Exception as e:
            log.error("memory_stats_failed", error=str(e))
            return {"total": 0}


memory_service = MemoryService()
