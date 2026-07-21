# ====================================================================
# JARVIS OMEGA - Notes + Todo Plugin (local markdown + SQLite)
# ====================================================================
"""
Phase 10 plugin: local-only notes and todos. No external service.

  * Notes are markdown files in ``./storage/notes``.
  * Todos live in a SQLite DB at ``./storage/todos.db``.

  Tools:
    notes.create / list / read / search
    todo.add / list / complete / delete
"""

from __future__ import annotations

import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.tools import tool, RiskTier


_NOTES_DIR = Path("./storage/notes")
_TODOS_DB = Path("./storage/todos.db")


def _notes_dir() -> Path:
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return _NOTES_DIR


def _safe_filename(name: str) -> str:
    """Slugify a note title to a safe filename."""
    safe = "".join(c for c in name.lower() if c.isalnum() or c in " -_").strip()
    safe = safe.replace(" ", "-")
    return safe or "untitled"


# --------------------------------------------------------------------
# Notes (markdown files)
# --------------------------------------------------------------------

@tool(
    name="notes.create",
    description="Create a markdown note. Returns the file path.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "default": ""},
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["title"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="notes",
)
async def notes_create(title: str, content: str = "", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    tags = tags or []
    fname = f"{_safe_filename(title)}.md"
    path = _notes_dir() / fname
    header = f"# {title}\n\n_Tags: {', '.join(tags) if tags else '(none)'}_\n_Created: {datetime.utcnow().isoformat()}_\n\n"
    path.write_text(header + content + "\n", encoding="utf-8")
    return {"ok": True, "title": title, "file": str(path), "bytes": len(header) + len(content)}


@tool(
    name="notes.list",
    description="List all notes.",
    parameters={"type": "object"},
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="notes",
)
async def notes_list() -> Dict[str, Any]:
    files = sorted(_notes_dir().glob("*.md"))
    return {
        "ok": True,
        "count": len(files),
        "notes": [f.name for f in files],
        "dir": str(_notes_dir()),
    }


@tool(
    name="notes.read",
    description="Read a note by filename.",
    parameters={
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="notes",
)
async def notes_read(filename: str) -> Dict[str, Any]:
    path = _notes_dir() / filename
    if not path.is_file():
        return {"ok": False, "error": f"note not found: {filename}"}
    return {"ok": True, "filename": filename, "content": path.read_text(encoding="utf-8")}


@tool(
    name="notes.search",
    description="Full-text search across all notes. Returns matching filenames + a snippet.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="notes",
)
async def notes_search(query: str, max_results: int = 20) -> Dict[str, Any]:
    q = query.lower()
    matches: List[Dict[str, Any]] = []
    for f in _notes_dir().glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
            if q in text.lower():
                idx = text.lower().find(q)
                snippet = text[max(0, idx - 60):idx + len(q) + 60]
                matches.append({"filename": f.name, "snippet": snippet})
                if len(matches) >= max_results:
                    break
        except Exception:
            continue
    return {"ok": True, "query": query, "count": len(matches), "matches": matches}


# --------------------------------------------------------------------
# Todos (SQLite)
# --------------------------------------------------------------------

def _init_db() -> None:
    _TODOS_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_TODOS_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                completed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )


@tool(
    name="todo.add",
    description="Add a todo item. Priority can be low/medium/high/critical.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
        },
        "required": ["text"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="todo",
)
async def todo_add(text: str, priority: str = "medium") -> Dict[str, Any]:
    def _do():
        _init_db()
        with sqlite3.connect(_TODOS_DB) as conn:
            cur = conn.execute(
                "INSERT INTO todos (text, priority, created_at) VALUES (?, ?, ?)",
                (text, priority, datetime.utcnow().isoformat()),
            )
            return cur.lastrowid
    row_id = await asyncio.to_thread(_do)
    return {"ok": True, "id": row_id, "text": text, "priority": priority}


@tool(
    name="todo.list",
    description="List todos. Filter by status / priority.",
    parameters={
        "type": "object",
        "properties": {
            "include_completed": {"type": "boolean", "default": False},
            "priority": {"type": "string", "default": "", "description": "Optional filter."},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="todo",
)
async def todo_list(include_completed: bool = False, priority: str = "") -> Dict[str, Any]:
    def _do():
        _init_db()
        sql = "SELECT id, text, priority, completed, created_at, completed_at FROM todos"
        clauses = []
        if not include_completed:
            clauses.append("completed = 0")
        if priority:
            clauses.append(f"priority = '{priority}'")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        with sqlite3.connect(_TODOS_DB) as conn:
            rows = conn.execute(sql).fetchall()
        return [
            {
                "id": r[0], "text": r[1], "priority": r[2],
                "completed": bool(r[3]), "created_at": r[4], "completed_at": r[5],
            }
            for r in rows
        ]
    todos = await asyncio.to_thread(_do)
    return {"ok": True, "count": len(todos), "todos": todos}


@tool(
    name="todo.complete",
    description="Mark a todo as completed by ID.",
    parameters={
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="todo",
)
async def todo_complete(id: int) -> Dict[str, Any]:
    def _do():
        _init_db()
        with sqlite3.connect(_TODOS_DB) as conn:
            cur = conn.execute(
                "UPDATE todos SET completed = 1, completed_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), id),
            )
            return cur.rowcount
    n = await asyncio.to_thread(_do)
    return {"ok": n > 0, "id": id, "updated_rows": n}


@tool(
    name="todo.delete",
    description="Delete a todo by ID.",
    parameters={
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
    risk_tier=RiskTier.TIER_3_DESTRUCTIVE,
    category="todo",
)
async def todo_delete(id: int) -> Dict[str, Any]:
    def _do():
        _init_db()
        with sqlite3.connect(_TODOS_DB) as conn:
            cur = conn.execute("DELETE FROM todos WHERE id = ?", (id,))
            return cur.rowcount
    n = await asyncio.to_thread(_do)
    return {"ok": n > 0, "id": id, "deleted_rows": n}


PLUGIN_NAME = "notes_todo"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Local markdown notes + SQLite todos."
