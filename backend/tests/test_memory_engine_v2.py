# ====================================================================
# JARVIS OMEGA — SQLite Memory Engine Unit Tests
# ====================================================================
"""
Unit tests for the zero-dependency SQLite + TF-IDF Memory Engine.
"""

import os
import shutil
import pytest
from pathlib import Path
from backend.memory.sqlite_memory import SqliteMemoryEngine
from shared.constants import MemoryCategory
from shared.models import MemoryEntry, MemoryQuery

TEST_DB_DIR = Path("./storage/test_temp")
TEST_DB_PATH = TEST_DB_DIR / "test_jarvis_omega.db"

@pytest.fixture
async def memory_engine():
    # Setup
    if TEST_DB_DIR.exists():
        shutil.rmtree(TEST_DB_DIR)
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
    
    engine = SqliteMemoryEngine(db_path=str(TEST_DB_PATH))
    await engine.initialize()
    
    yield engine
    
    # Teardown
    await engine.close()
    if TEST_DB_DIR.exists():
        shutil.rmtree(TEST_DB_DIR)

@pytest.mark.anyio
async def test_memory_lifecycle(memory_engine):
    """Test standard flow of storing, retrieving, searching, pinning, updating, and deleting memories."""
    # 1. Add memories
    mem1_id = await memory_engine.add(
        content="Sir likes to use Next.js with Tailwind CSS for his web projects.",
        category=MemoryCategory.PREFERENCES,
        source="unit_test",
        tags=["frontend", "nextjs"],
        metadata={"project": "web_hub"}
    )
    
    mem2_id = await memory_engine.add(
        content="The main server deployment failed because the database connection timed out after 30 seconds.",
        category=MemoryCategory.DEBUGGING,
        source="unit_test",
        tags=["deployment", "database", "timeout"]
    )
    
    assert mem1_id.startswith("mem_")
    assert mem2_id.startswith("mem_")
    assert mem1_id != mem2_id
    
    # Dedup check
    dup_id = await memory_engine.add(
        content="Sir likes to use Next.js with Tailwind CSS for his web projects.",
        category=MemoryCategory.PREFERENCES,
        source="unit_test"
    )
    assert dup_id == mem1_id

    # 2. Get single memory
    mem1 = await memory_engine.get(mem1_id)
    assert mem1 is not None
    assert mem1.content == "Sir likes to use Next.js with Tailwind CSS for his web projects."
    assert mem1.category == MemoryCategory.PREFERENCES
    assert "frontend" in mem1.tags
    assert mem1.metadata.get("project") == "web_hub"
    assert mem1.pinned is False

    # 3. Get stats
    stats = await memory_engine.get_stats()
    assert stats[MemoryCategory.PREFERENCES.value] == 1
    assert stats[MemoryCategory.DEBUGGING.value] == 1
    assert stats["total"] == 2

    # 4. Search and verify TF-IDF vector relevance
    # A query with "Next.js Tailwind" should match the first memory highly
    query_1 = MemoryQuery(query="Next.js and Tailwind CSS templates", categories=[MemoryCategory.PREFERENCES])
    results_1 = await memory_engine.search(query_1)
    assert len(results_1) > 0
    assert results_1[0].memory_id == mem1_id
    assert results_1[0].relevance_score > 0.0

    # A query with "database timeout" should match the second memory highly
    query_2 = MemoryQuery(query="database connection timeout on deployment", categories=[MemoryCategory.DEBUGGING])
    results_2 = await memory_engine.search(query_2)
    assert len(results_2) > 0
    assert results_2[0].memory_id == mem2_id
    
    # 5. Pinned feature
    pin_success = await memory_engine.pin(mem1_id, pinned=True)
    assert pin_success is True
    mem1_updated = await memory_engine.get(mem1_id)
    assert mem1_updated.pinned is True

    # 6. Update memory content
    update_success = await memory_engine.update(
        memory_id=mem1_id,
        category=MemoryCategory.PREFERENCES,
        content="Sir prefers Next.js with vanilla CSS over Tailwind.",
        metadata={"project": "web_hub_v2"}
    )
    assert update_success is True
    mem1_edited = await memory_engine.get(mem1_id)
    assert mem1_edited.content == "Sir prefers Next.js with vanilla CSS over Tailwind."
    assert mem1_edited.metadata.get("project") == "web_hub_v2"

    # 7. Delete memory
    delete_success = await memory_engine.delete(mem1_id)
    assert delete_success is True
    assert await memory_engine.get(mem1_id) is None
    
    stats_after = await memory_engine.get_stats()
    assert stats_after[MemoryCategory.PREFERENCES.value] == 0
    assert stats_after["total"] == 1
