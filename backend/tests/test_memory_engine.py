# ====================================================================
# JARVIS OMEGA — Memory Engine Tests
# ====================================================================
"""
Smoke tests for the ChromaDB-backed memory engine using the real persistent
client (temp directory per test). These verify the engine initializes, stores,
queries, updates, deletes, and reports stats correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.memory_engine import MemoryEngine
from shared.constants import MemoryCategory
from shared.models import MemoryEntry, MemoryQuery


@pytest.fixture
async def engine(tmp_path: Path) -> MemoryEngine:
    e = MemoryEngine(persist_dir=str(tmp_path / "chroma"))
    await e.initialize()
    return e


@pytest.mark.asyncio
async def test_engine_initializes_with_collections(engine: MemoryEngine):
    stats = await engine.get_stats()
    # Every MemoryCategory should be present with count 0 on a fresh engine.
    assert isinstance(stats, dict)
    assert len(stats) > 0
    assert all(v == 0 for v in stats.values())


@pytest.mark.asyncio
async def test_store_and_query_round_trip(engine: MemoryEngine):
    entry = MemoryEntry(
        category=MemoryCategory.CONVERSATIONS,
        content="Sir requested a deploy of the backend service.",
        source="test",
        tags=["deploy"],
    )
    mid = await engine.store(entry)
    assert mid

    results = await engine.query(MemoryQuery(
        query="backend deploy",
        categories=[MemoryCategory.CONVERSATIONS],
        top_k=5,
    ))
    assert len(results) >= 1
    assert any(r.memory_id == mid for r in results)


@pytest.mark.asyncio
async def test_delete_removes_entry(engine: MemoryEngine):
    entry = MemoryEntry(
        category=MemoryCategory.DEBUGGING,
        content="temporary debug note",
        source="test",
    )
    mid = await engine.store(entry)
    ok = await engine.delete(mid, MemoryCategory.DEBUGGING)
    assert ok is True
    remaining = await engine.get_all(MemoryCategory.DEBUGGING, limit=10)
    assert all(r.memory_id != mid for r in remaining)


@pytest.mark.asyncio
async def test_update_changes_content(engine: MemoryEngine):
    entry = MemoryEntry(
        category=MemoryCategory.PROJECTS,
        content="initial project note",
        source="test",
    )
    mid = await engine.store(entry)
    ok = await engine.update(mid, MemoryCategory.PROJECTS, content="updated note")
    assert ok is True
    entries = await engine.get_all(MemoryCategory.PROJECTS, limit=10)
    updated = next(e for e in entries if e.memory_id == mid)
    assert "updated" in updated.content


@pytest.mark.asyncio
async def test_stats_reflects_inserts(engine: MemoryEngine):
    for i in range(3):
        await engine.store(MemoryEntry(
            category=MemoryCategory.TASKS,
            content=f"task note {i}",
            source="test",
        ))
    stats = await engine.get_stats()
    assert stats.get(MemoryCategory.TASKS.value) == 3
