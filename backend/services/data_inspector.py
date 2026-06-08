"""
Data Inspector — SQLAlchemy core schema reflection + parameterized raw queries.

# pip install: sqlalchemy
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, inspect, text

from shared.logger import get_logger

log = get_logger("data_inspector")

_DB_PATH = Path.home() / ".jarvis" / "jarvis.db"


class DataInspector:
    """
    Reflects SQLAlchemy schema and executes parameterized queries.
    """

    def __init__(self):
        self._engine = None
        self._db_path = _DB_PATH

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = create_engine(f"sqlite:///{self._db_path}")

    def get_schema(self) -> Dict[str, List[Dict]]:
        """Reflect the database schema."""
        self._ensure_engine()
        inspector = inspect(self._engine)
        schema = {}
        for table_name in inspector.get_table_names():
            columns = inspector.get_columns(table_name)
            schema[table_name] = [
                {"name": c["name"], "type": str(c["type"]), "nullable": c.get("nullable", True)}
                for c in columns
            ]
        return schema

    def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Execute a parameterized raw SQL query."""
        self._ensure_engine()
        with self._engine.connect() as conn:
            result = conn.execute(text(query), parameters=params or {})
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return rows

    def execute_query_safe(self, query: str) -> List[Dict]:
        """Execute query with SQLite safety mechanisms."""
        # Only allow SELECT queries
        stripped = query.strip().upper()
        if not stripped.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed via data_inspector")
        return self.execute_query(query)


data_inspector = DataInspector()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.data_inspector import data_inspector
# schema = data_inspector.get_schema()
# rows = data_inspector.execute_query("SELECT * FROM messages LIMIT 5")
# print(rows)
# ---
