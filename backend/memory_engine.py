# ====================================================================
# JARVIS OMEGA — Memory Engine (ChromaDB with SQLite Fallback)
# ====================================================================
"""
ChromaDB integration: 10 dedicated collections, semantic similarity
search, memory storage/retrieval, and SHA-256 hash-based dedup.
Gracefully falls back to a local SQLite database if chromadb is not installed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

from shared.constants import MemoryCategory
from shared.logger import get_logger
from shared.models import MemoryContext, MemoryEntry, MemoryQuery

log = get_logger("memory_engine")

# Collection names matching the spec
COLLECTIONS = [cat.value for cat in MemoryCategory]


class MemoryEngine:
    """
    Persistent memory architecture using ChromaDB, with a zero-dep SQLite fallback.
    Manages 10 dedicated collections with semantic search.
    """

    def __init__(self, persist_dir: str = "./storage/chromadb") -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client: Optional[Any] = None
        self._collections: Dict[str, Any] = {}
        self._hash_cache: Dict[str, str] = {}  # SHA-256 dedup cache
        self._sqlite_conn: Optional[sqlite3.Connection] = None

    async def initialize(self) -> None:
        """Initialize ChromaDB client or SQLite fallback and prepare collections."""
        log.info("memory_engine_init", persist_dir=str(self._persist_dir), chroma_available=CHROMA_AVAILABLE)

        if CHROMA_AVAILABLE:
            try:
                self._client = chromadb.PersistentClient(
                    path=str(self._persist_dir),
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )

                for collection_name in COLLECTIONS:
                    self._collections[collection_name] = self._client.get_or_create_collection(
                        name=collection_name,
                        metadata={"hnsw:space": "cosine"},
                    )
                    count = self._collections[collection_name].count()
                    log.info("collection_ready", name=collection_name, count=count)

                log.info("memory_engine_ready", collections=len(self._collections))
                return
            except Exception as e:
                log.warning("chromadb_init_failed_falling_back_to_sqlite", error=str(e))

        # SQLite Fallback Initialization
        db_path = self._persist_dir / "memory_fallback.db"
        self._sqlite_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._sqlite_conn.row_factory = sqlite3.Row
        cursor = self._sqlite_conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                category TEXT,
                content TEXT,
                source TEXT,
                tags TEXT,
                pinned INTEGER,
                created_at TEXT,
                updated_at TEXT,
                content_hash TEXT,
                metadata TEXT
            )
        """)
        self._sqlite_conn.commit()
        log.info("memory_engine_ready_sqlite_fallback")

    async def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry. Returns memory_id."""
        # Dedup check via content hash
        content_hash = hashlib.sha256(entry.content.encode()).hexdigest()
        if content_hash in self._hash_cache:
            log.debug("memory_dedup_hit", hash=content_hash[:12])
            return self._hash_cache[content_hash]

        if CHROMA_AVAILABLE and self._client is not None:
            collection = self._collections.get(entry.category.value)
            if collection:
                metadata = {
                    "source": entry.source,
                    "tags": json.dumps(entry.tags),
                    "pinned": entry.pinned,
                    "created_at": entry.created_at.isoformat(),
                    "updated_at": entry.updated_at.isoformat(),
                    "content_hash": content_hash,
                    **{k: str(v) for k, v in entry.metadata.items()},
                }

                collection.upsert(
                    ids=[entry.memory_id],
                    documents=[entry.content],
                    metadatas=[metadata],
                )

                self._hash_cache[content_hash] = entry.memory_id
                log.info("memory_stored_chroma", memory_id=entry.memory_id, category=entry.category.value)
                return entry.memory_id

        # SQLite Fallback Store
        if self._sqlite_conn:
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO memories
                (memory_id, category, content, source, tags, pinned, created_at, updated_at, content_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.memory_id,
                    entry.category.value,
                    entry.content,
                    entry.source,
                    json.dumps(entry.tags),
                    1 if entry.pinned else 0,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                    content_hash,
                    json.dumps(entry.metadata),
                )
            )
            self._sqlite_conn.commit()
            self._hash_cache[content_hash] = entry.memory_id
            log.info("memory_stored_sqlite", memory_id=entry.memory_id, category=entry.category.value)
            return entry.memory_id

        return ""

    async def query(self, query: MemoryQuery) -> List[MemoryEntry]:
        """Semantic search (ChromaDB) or SQL LIKE search (SQLite) across memory categories."""
        results: List[MemoryEntry] = []
        categories = query.categories or list(MemoryCategory)

        if CHROMA_AVAILABLE and self._client is not None:
            for category in categories:
                cat_val = category.value if isinstance(category, MemoryCategory) else category
                collection = self._collections.get(cat_val)
                if not collection or collection.count() == 0:
                    continue

                try:
                    search_results = collection.query(
                        query_texts=[query.query],
                        n_results=min(query.top_k, collection.count()),
                    )

                    if search_results and search_results["documents"]:
                        for i, doc in enumerate(search_results["documents"][0]):
                            meta = search_results["metadatas"][0][i] if search_results["metadatas"] else {}
                            distance = search_results["distances"][0][i] if search_results["distances"] else 1.0
                            relevance = max(0.0, 1.0 - distance)

                            if relevance < query.min_relevance:
                                continue

                            entry = MemoryEntry(
                                memory_id=search_results["ids"][0][i],
                                category=MemoryCategory(cat_val),
                                content=doc,
                                source=meta.get("source", ""),
                                tags=json.loads(meta.get("tags", "[]")),
                                pinned=meta.get("pinned", False),
                                relevance_score=relevance,
                                metadata={k: v for k, v in meta.items() if k not in ("source", "tags", "pinned", "created_at", "updated_at", "content_hash")},
                            )
                            results.append(entry)
                except Exception as e:
                    log.error("memory_query_error", category=cat_val, error=str(e))

            # Sort by relevance
            results.sort(key=lambda x: x.relevance_score, reverse=True)
            return results[:query.top_k]

        # SQLite Fallback Query
        if self._sqlite_conn:
            cursor = self._sqlite_conn.cursor()
            for category in categories:
                cat_val = category.value if isinstance(category, MemoryCategory) else category
                # Simple keyword match or retrieve recent if empty query
                if query.query.strip():
                    cursor.execute(
                        "SELECT * FROM memories WHERE category = ? AND (content LIKE ? OR source LIKE ? OR tags LIKE ?)",
                        (cat_val, f"%{query.query}%", f"%{query.query}%", f"%{query.query}%")
                    )
                else:
                    cursor.execute("SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC", (cat_val,))

                rows = cursor.fetchall()
                for r in rows:
                    results.append(MemoryEntry(
                        memory_id=r["memory_id"],
                        category=MemoryCategory(r["category"]),
                        content=r["content"],
                        source=r["source"],
                        tags=json.loads(r["tags"]),
                        pinned=bool(r["pinned"]),
                        relevance_score=1.0,  # default relevance score for fallback
                        metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                    ))

            # For fallback, sort pinned first, then by memory_id or date
            results.sort(key=lambda x: (x.pinned, x.memory_id), reverse=True)
            return results[:query.top_k]

        return []

    async def build_context(self, query_text: str) -> MemoryContext:
        """
        Build complete memory context for LLM reasoning.
        Retrieves top memories across all required categories.
        """
        general = await self.query(MemoryQuery(query=query_text, top_k=10))

        project_memories = await self.query(MemoryQuery(
            query=query_text,
            categories=[MemoryCategory.PROJECTS, MemoryCategory.CODE],
            top_k=5,
        ))

        task_memories = await self.query(MemoryQuery(
            query=query_text,
            categories=[MemoryCategory.TASKS],
            top_k=5,
        ))

        debug_memories = await self.query(MemoryQuery(
            query=query_text,
            categories=[MemoryCategory.DEBUGGING],
            top_k=5,
        ))

        pref_memories = await self.query(MemoryQuery(
            query=query_text,
            categories=[MemoryCategory.PREFERENCES],
            top_k=5,
        ))

        return MemoryContext(
            general_memories=general,
            project_memories=project_memories,
            task_memories=task_memories,
            debugging_memories=debug_memories,
            preference_memories=pref_memories,
        )

    async def delete(self, memory_id: str, category: MemoryCategory) -> bool:
        """Delete a specific memory entry."""
        if CHROMA_AVAILABLE and self._client is not None:
            collection = self._collections.get(category.value)
            if collection:
                try:
                    collection.delete(ids=[memory_id])
                    log.info("memory_deleted_chroma", memory_id=memory_id, category=category.value)
                    return True
                except Exception as e:
                    log.error("memory_delete_error_chroma", error=str(e))

        # SQLite Fallback Delete
        if self._sqlite_conn:
            try:
                cursor = self._sqlite_conn.cursor()
                cursor.execute("DELETE FROM memories WHERE memory_id = ? AND category = ?", (memory_id, category.value))
                self._sqlite_conn.commit()
                log.info("memory_deleted_sqlite", memory_id=memory_id, category=category.value)
                return True
            except Exception as e:
                log.error("memory_delete_error_sqlite", error=str(e))

        return False

    async def update(self, memory_id: str, category: MemoryCategory, content: str, metadata: Optional[Dict] = None) -> bool:
        """Update an existing memory entry."""
        if CHROMA_AVAILABLE and self._client is not None:
            collection = self._collections.get(category.value)
            if collection:
                try:
                    update_meta = metadata or {}
                    update_meta["updated_at"] = datetime.utcnow().isoformat()
                    collection.update(
                        ids=[memory_id],
                        documents=[content],
                        metadatas=[{k: str(v) for k, v in update_meta.items()}],
                    )
                    log.info("memory_updated_chroma", memory_id=memory_id)
                    return True
                except Exception as e:
                    log.error("memory_update_error_chroma", error=str(e))

        # SQLite Fallback Update
        if self._sqlite_conn:
            try:
                cursor = self._sqlite_conn.cursor()
                now_iso = datetime.utcnow().isoformat()
                cursor.execute(
                    "UPDATE memories SET content = ?, updated_at = ?, metadata = ? WHERE memory_id = ? AND category = ?",
                    (content, now_iso, json.dumps(metadata or {}), memory_id, category.value)
                )
                self._sqlite_conn.commit()
                log.info("memory_updated_sqlite", memory_id=memory_id)
                return True
            except Exception as e:
                log.error("memory_update_error_sqlite", error=str(e))

        return False

    async def get_all(self, category: MemoryCategory, limit: int = 100) -> List[MemoryEntry]:
        """Get all memories in a category."""
        if CHROMA_AVAILABLE and self._client is not None:
            collection = self._collections.get(category.value)
            if collection and collection.count() > 0:
                try:
                    results = collection.get(limit=min(limit, collection.count()))
                    entries = []
                    for i, doc in enumerate(results["documents"]):
                        meta = results["metadatas"][i] if results["metadatas"] else {}
                        entries.append(MemoryEntry(
                            memory_id=results["ids"][i],
                            category=category,
                            content=doc,
                            source=meta.get("source", ""),
                            tags=json.loads(meta.get("tags", "[]")),
                            pinned=meta.get("pinned", False),
                        ))
                    return entries
                except Exception as e:
                    log.error("memory_get_all_error_chroma", error=str(e))

        # SQLite Fallback Get All
        if self._sqlite_conn:
            try:
                cursor = self._sqlite_conn.cursor()
                cursor.execute("SELECT * FROM memories WHERE category = ? LIMIT ?", (category.value, limit))
                rows = cursor.fetchall()
                entries = []
                for r in rows:
                    entries.append(MemoryEntry(
                        memory_id=r["memory_id"],
                        category=category,
                        content=r["content"],
                        source=r["source"],
                        tags=json.loads(r["tags"]),
                        pinned=bool(r["pinned"]),
                    ))
                return entries
            except Exception as e:
                log.error("memory_get_all_error_sqlite", error=str(e))

        return []

    async def get_stats(self) -> Dict[str, int]:
        """Get memory counts per collection."""
        stats = {}
        if CHROMA_AVAILABLE and self._client is not None:
            for name, collection in self._collections.items():
                stats[name] = collection.count()
            return stats

        # SQLite Fallback Stats
        if self._sqlite_conn:
            cursor = self._sqlite_conn.cursor()
            for cat in COLLECTIONS:
                cursor.execute("SELECT COUNT(*) as cnt FROM memories WHERE category = ?", (cat,))
                stats[cat] = cursor.fetchone()["cnt"]
            return stats

        return {cat: 0 for cat in COLLECTIONS}

    def check_document_hash(self, file_path: str) -> Optional[str]:
        """Check if a document has already been processed (SHA-256 cache)."""
        from shared.security import sha256_file
        file_hash = sha256_file(file_path)
        return self._hash_cache.get(file_hash)

    def register_document_hash(self, file_path: str, memory_id: str) -> None:
        """Register a processed document hash."""
        from shared.security import sha256_file
        file_hash = sha256_file(file_path)
        self._hash_cache[file_hash] = memory_id


# Global memory engine instance
memory_engine = MemoryEngine()
