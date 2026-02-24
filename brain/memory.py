# =============================================================================
# brain/memory.py — SQLite persistent memory (key-value store)
# =============================================================================

import sqlite3
import os
from config import DB_PATH, SUMMARY_MAX_LENGTH, SUMMARY_TRIM_LENGTH

def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            key   TEXT    UNIQUE NOT NULL,
            value TEXT    NOT NULL
        )
    """)
    conn.commit()

def get(key):
    with _connect() as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT value FROM memory WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None

def set(key, value):
    with _connect() as conn:
        _ensure_table(conn)
        conn.execute("""
            INSERT INTO memory (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()

def delete(key):
    with _connect() as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM memory WHERE key = ?", (key,))
        conn.commit()

def append_to_summary(new_sentence):
    existing = get("short_conversation_summary") or ""
    if len(existing) > SUMMARY_MAX_LENGTH:
        existing = existing[-SUMMARY_TRIM_LENGTH:]
    updated = (existing + " " + new_sentence).strip()
    set("short_conversation_summary", updated)

def get_summary():
    return get("short_conversation_summary") or ""
