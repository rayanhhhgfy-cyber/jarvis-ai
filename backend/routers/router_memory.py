# ====================================================================
# JARVIS OMEGA — Memory Router
# ====================================================================
"""
REST endpoints for memory operations: semantic search, CRUD management,
pinning, and metadata indexing.
"""

from __future__ import annotations

from typing import List, Dict

from fastapi import APIRouter, HTTPException, Query, status

from shared.models import MemoryEntry, MemoryQuery
from shared.constants import MemoryCategory
from backend.services.memory_service import memory_service
from shared.logger import get_logger

log = get_logger("router_memory")
router = APIRouter(prefix="/api/memory", tags=["Memory"])


@router.post("/query", response_model=List[MemoryEntry])
async def semantic_query(query: MemoryQuery):
    """Search memory collections using semantic embeddings."""
    try:
        return await memory_service.search_memories(query)
    except Exception as e:
        log.error("memory_query_api_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {str(e)}",
        )


@router.post("", response_model=Dict[str, str])
async def store_new_memory(entry: MemoryEntry):
    """Store a memory entry in ChromaDB."""
    try:
        memory_id = await memory_service.add_memory(
            content=entry.content,
            category=entry.category,
            source=entry.source or "api_request",
            tags=entry.tags,
            metadata=entry.metadata,
            pinned=entry.pinned,
        )
        return {"memory_id": memory_id}
    except Exception as e:
        log.error("memory_store_api_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Store failed: {str(e)}",
        )


@router.get("/stats")
async def fetch_memory_stats():
    """Retrieve counts per memory collection."""
    return await memory_service.get_stats()


@router.get("/{category}", response_model=List[MemoryEntry])
async def list_memories_by_category(category: MemoryCategory, limit: int = 100):
    """Get all memories in a specific category collection."""
    from backend.memory_engine import memory_engine
    return await memory_engine.get_all(category, limit=limit)


@router.delete("/{category}/{memory_id}")
async def delete_memory(category: MemoryCategory, memory_id: str):
    """Delete a specific memory entry."""
    success = await memory_service.delete_memory(memory_id, category)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or delete failed",
        )
    return {"status": "deleted"}


@router.put("/{category}/{memory_id}")
async def update_memory(category: MemoryCategory, memory_id: str, content: str, metadata: Dict = None):
    """Update content/metadata of a specific memory."""
    success = await memory_service.update_memory(memory_id, category, content, metadata)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or update failed",
        )
    return {"status": "updated"}


@router.post("/{category}/{memory_id}/pin")
async def pin_memory(category: MemoryCategory, memory_id: str):
    """Pin a memory entry to prevent automatic consolidation cleanup."""
    success = await memory_service.pin_memory(memory_id, category, pinned=True)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or pinning failed",
        )
    return {"status": "pinned"}


@router.post("/{category}/{memory_id}/unpin")
async def unpin_memory(category: MemoryCategory, memory_id: str):
    """Unpins a memory entry to allow automatic consolidation cleanup."""
    success = await memory_service.pin_memory(memory_id, category, pinned=False)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory entry not found or unpinning failed",
        )
    return {"status": "unpinned"}
