# ====================================================================
# JARVIS OMEGA — DM Stores (scheduled messages, reminders, contacts)
# ====================================================================
"""
Tiny JSON-file stores for Jarvis's DM abilities. Each store is one file
under ``storage/`` and one in-memory dict, loaded on first use and
saved on every change. Render's disk is ephemeral (wiped on redeploy),
so these are best-effort: a scheduled message or reminder set before a
redeploy may be lost. The caller always falls back gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.logger import get_logger

log = get_logger("dm_store")

_STORE_DIR = Path(__file__).resolve().parents[2] / "storage"


class JsonStore:
    """One JSON file holding a dict. Thread-safe enough for our use."""

    def __init__(self, filename: str) -> None:
        self._path = _STORE_DIR / filename
        self._data: dict[str, Any] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(self._data, dict):
                    self._data = {}
        except Exception as e:
            log.warning("dm_store_load_failed", path=str(self._path), error=str(e))
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            log.warning("dm_store_save_failed", path=str(self._path), error=str(e))

    def get(self, key: str, default: Any = None) -> Any:
        self._load()
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._load()
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        self._load()
        if key in self._data:
            del self._data[key]
            self._save()

    def all(self) -> dict[str, Any]:
        self._load()
        return dict(self._data)

    def clear(self) -> None:
        self._data = {}
        self._loaded = True
        self._save()


# One store per feature. Filenames are stable — do not rename.
scheduled_dms = JsonStore("scheduled_dms.json")
reminders = JsonStore("reminders.json")
contacts = JsonStore("contacts.json")
calendar = JsonStore("calendar.json")
