from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
SETTINGS_FILE = STORAGE_DIR / "user_settings.json"

DEFAULT_SETTINGS = {
    "persona": "adult",
    "custom_instructions_a": "",
    "custom_instructions_b": "",
    "custom_suggestions": "",
    "start_on_wakeup": False,
    "updated_at": "",
}


def _ensure_storage_dir():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _read_all() -> Dict[str, dict]:
    _ensure_storage_dir()
    if not SETTINGS_FILE.exists():
        return {}
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: Dict[str, dict]):
    _ensure_storage_dir()
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


def load(user_id: str = "default") -> dict:
    all_settings = _read_all()
    return all_settings.get(user_id, dict(DEFAULT_SETTINGS))


def save(user_id: str, settings: dict) -> dict:
    all_settings = _read_all()
    current = dict(DEFAULT_SETTINGS)
    current.update(settings)
    current["updated_at"] = datetime.utcnow().isoformat()
    all_settings[user_id] = current
    _write_all(all_settings)
    return current
