# ====================================================================
# JARVIS OMEGA — Memory Engine (ChromaDB)
# ====================================================================
"""
ChromaDB integration: 10 dedicated collections, semantic similarity
search, memory storage/retrieval, and SHA-256 hash-based dedup.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from shared.constants import MemoryCategory
from shared.logger import get_logger
from shared.models import MemoryContext, MemoryEntry, MemoryQuery

log = get_logger("memory_engine")

# Collection names matching the spec
COLLECTIONS = [cat.value for cat in MemoryCategory]


class MemoryEngine:
    """
    Persistent memory architecture using ChromaDB.
    Manages 10 dedicated collections with semantic search.
    """

    def __init__(self, persist_dir: str = "./storage/chromadb") -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client: Optional[chromadb.ClientAPI] = None
        self._collections: Dict[str, Any] = {}
        self._hash_cache: Dict[str, str] = {}  # SHA-256 dedup cache

    async def initialize(self) -> None:
        """Initialize ChromaDB client and create all collections."""
        log.info("memory_engine_init", persist_dir=str(self._persist_dir))

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

    async def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry. Returns memory_id."""
        collection = self._collections.get(entry.category.value)
        if not collection:
            log.error("invalid_collection", category=entry.category.value)
            return ""

        # Dedup check via content hash
        content_hash = hashlib.sha256(entry.content.encode()).hexdigest()
        if content_hash in self._hash_cache:
            log.debug("memory_dedup_hit", hash=content_hash[:12])
            return self._hash_cache[content_hash]

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

        log.info(
            "memory_stored",
            memory_id=entry.memory_id,
            category=entry.category.value,
            content_length=len(entry.content),
        )

        return entry.memory_id

    async def query(self, query: MemoryQuery) -> List[MemoryEntry]:
        """Semantic search across specified memory categories."""
        results: List[MemoryEntry] = []
        categories = query.categories or list(MemoryCategory)

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
        collection = self._collections.get(category.value)
        if not collection:
            return False
        try:
            collection.delete(ids=[memory_id])
            log.info("memory_deleted", memory_id=memory_id, category=category.value)
            return True
        except Exception as e:
            log.error("memory_delete_error", error=str(e))
            return False

    async def update(self, memory_id: str, category: MemoryCategory, content: str, metadata: Optional[Dict] = None) -> bool:
        """Update an existing memory entry."""
        collection = self._collections.get(category.value)
        if not collection:
            return False
        try:
            update_meta = metadata or {}
            update_meta["updated_at"] = datetime.utcnow().isoformat()
            collection.update(
                ids=[memory_id],
                documents=[content],
                metadatas=[{k: str(v) for k, v in update_meta.items()}],
            )
            log.info("memory_updated", memory_id=memory_id)
            return True
        except Exception as e:
            log.error("memory_update_error", error=str(e))
            return False

    async def get_all(self, category: MemoryCategory, limit: int = 100) -> List[MemoryEntry]:
        """Get all memories in a category."""
        collection = self._collections.get(category.value)
        if not collection or collection.count() == 0:
            return []

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
            log.error("memory_get_all_error", error=str(e))
            return []

    async def get_stats(self) -> Dict[str, int]:
        """Get memory counts per collection."""
        stats = {}
        for name, collection in self._collections.items():
            stats[name] = collection.count()
        return stats

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
