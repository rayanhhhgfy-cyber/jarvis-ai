import sqlite3, os
from config import DB_PATH, SUMMARY_MAX_LENGTH, SUMMARY_TRIM_LENGTH
try:
    from database.supabase_db import supabase_db
    USE_SUPABASE = os.getenv('USE_SUPABASE', 'false').lower() == 'true'
except ImportError:
    USE_SUPABASE = False
    supabase_db = None
def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def _table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL)""")
    c.commit()

def get(key):
    # Try Supabase if enabled
    if USE_SUPABASE and supabase_db:
        try:
            val = supabase_db.get_memory(key)
            if val is not None: return val
        except Exception as e:
            print(f"Supabase get failed: {e}")
    
    # Fallback to SQLite
    with _conn() as c:
        _table(c)
        r = c.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None

def set(key, value):
    # Try Supabase if enabled
    if USE_SUPABASE and supabase_db:
        try:
            supabase_db.set_memory(key, value)
        except Exception as e:
            print(f"Supabase set failed: {e}")
    
    # Always write to SQLite as well for local persistence/fallback
    with _conn() as c:
        _table(c)
        c.execute("""INSERT INTO memory(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (key, value))
        c.commit()

def delete(key):
    # Try Supabase if enabled
    if USE_SUPABASE and supabase_db:
        try:
            supabase_db.delete_memory(key)
        except Exception as e:
            print(f"Supabase delete failed: {e}")
    
    # Fallback to SQLite
    with _conn() as c:
        _table(c)
        c.execute("DELETE FROM memory WHERE key=?", (key,))
        c.commit()

def append_to_summary(s):
    ex = get("short_conversation_summary") or ""
    if len(ex) > SUMMARY_MAX_LENGTH:
        ex = ex[-SUMMARY_TRIM_LENGTH:]
    set("short_conversation_summary", (ex + " " + s).strip())

def get_summary():
    return get("short_conversation_summary") or ""
