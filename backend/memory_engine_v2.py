# ====================================================================
# JARVIS OMEGA — Memory Engine V2 Re-export
# ====================================================================
"""
Routes all legacy memory_engine imports to the new sqlite_memory implementation,
ensuring all features share the same underlying SQLite TF-IDF memory.
"""

from __future__ import annotations

from backend.memory.sqlite_memory import sqlite_memory as memory_engine

__all__ = ["memory_engine"]
