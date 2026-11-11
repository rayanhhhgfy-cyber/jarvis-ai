# ====================================================================
# JARVIS OMEGA — DM Stores (scheduled messages, reminders, contacts)
# ====================================================================
"""
Tiny JSON-file stores for Jarvis's DM abilities. Each store is one file
under ``storage/`` and one in-memory dict, loaded on first use and
saved on every change.

Durability: every store is ALSO mirrored to Turso (table ``dm_<name>``,
one per store) whenever ``TURSO_DATABASE_URL`` + ``TURSO_AUTH_TOKEN``
are set. Render's disk is ephemeral (wiped on redeploy), so the local
file alone is best-effort; Turso is the copy that survives. The mirror
is strictly best-effort — a Turso failure is logged and the local file
still holds the write, and the next save re-syncs the full store.
Load rule: a local file that exists and parses is trusted (it holds
every write); Turso is only used to restore a store whose local file
is missing (fresh deploy) or unreadable. That keeps a locally-deleted
key (a fired reminder) from being resurrected by a stale Turso row.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.logger import get_logger

log = get_logger("dm_store")

_STORE_DIR = Path(__file__).resolve().parents[2] / "storage"

# Turso mirror: one table per store, created on first use. A short
# timeout so a slow Turso never stalls a DM reply.
_TURSO_TIMEOUT = 5.0
_turso_clients: dict[str, Any] = {}
_turso_ensured: set[str] = set()
# Test hook: tests set this to a mock httpx transport so the Turso
# mirror can be exercised without the network. Production leaves it None.
_test_turso_transport: Any | None = None


def _turso_for_table(table: str) -> Any | None:
    """A Turso store for ``table``, or None when Turso is not configured.

    Cached per table; a bad config or missing env disables the mirror
    for the process (local files keep working exactly as before).
    """
    if table in _turso_clients:
        return _turso_clients[table]
    client: Any | None = None
    try:
        from backend.config import settings
        from backend.services.credentials_vault import _TursoStore

        url = settings.turso_database_url
        token = settings.turso_auth_token
        if url and token:
            client = _TursoStore(
                url, token, table,
                transport=_test_turso_transport,
                timeout=_TURSO_TIMEOUT,
            )
    except (ImportError, ValueError) as e:
        log.warning("dm_store_turso_unavailable", table=table, error=str(e))
        client = None
    _turso_clients[table] = client
    return client


def _turso_table_for(filename: str) -> str:
    """Table name for a store file: reminders.json -> dm_reminders."""
    return "dm_" + filename[:-5] if filename.endswith(".json") else "dm_" + filename


class JsonStore:
    """One JSON file holding a dict. Thread-safe enough for our use."""

    def __init__(self, filename: str) -> None:
        self._path = _STORE_DIR / filename
        self._data: dict[str, Any] = {}
        self._loaded = False
        self._turso_table = _turso_table_for(filename)

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        local_ok = False
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(self._data, dict):
                    self._data = {}
                else:
                    local_ok = True
        except Exception as e:
            log.warning("dm_store_load_failed", path=str(self._path), error=str(e))
            self._data = {}
        if not local_ok:
            # No usable local file (fresh deploy wiped it): restore
            # from Turso, the copy that survives redeploys.
            restored = self._load_turso()
            if restored:
                self._data = restored
                # Persist the restore locally so the next load is fast.
                self._save_local()

    def _load_turso(self) -> dict[str, Any] | None:
        client = _turso_for_table(self._turso_table)
        if client is None:
            return None
        try:
            if self._turso_table not in _turso_ensured:
                client.ensure_table()
                _turso_ensured.add(self._turso_table)
            entries = client.load_all()
            if entries:
                log.info(
                    "dm_store_restored_turso",
                    table=self._turso_table,
                    count=len(entries),
                )
            return dict(entries)
        except (RuntimeError, ValueError) as e:
            log.warning(
                "dm_store_turso_load_failed",
                table=self._turso_table,
                error=str(e),
            )
            return None

    def _save_local(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            log.warning("dm_store_save_failed", path=str(self._path), error=str(e))

    def _save_turso(self) -> None:
        client = _turso_for_table(self._turso_table)
        if client is None:
            return
        try:
            if self._turso_table not in _turso_ensured:
                client.ensure_table()
                _turso_ensured.add(self._turso_table)
            client.save_all(self._data)
        except (RuntimeError, TypeError, ValueError) as e:
            # Best-effort only: the local file already holds the write,
            # and the next save re-syncs the full store.
            log.warning(
                "dm_store_turso_save_failed",
                table=self._turso_table,
                error=str(e),
            )

    def _save(self) -> None:
        self._save_local()
        self._save_turso()

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
# Custom auto-reply rules: rule_id -> {person, topic, reply}.
rules = JsonStore("dm_rules.json")
# Pending meetings: thread_id -> {platform, sender_name, offered, awaiting}.
meetings = JsonStore("pending_meetings.json")
# Jarvis settings Sir sets on Telegram: {birthday_message, group_welcome_message}.
settings = JsonStore("dm_settings.json")
# Morning briefing settings Sir sets by chat: {time, voice, language,
# sections: {weather, news, calendar, birthdays, dms}}.
briefing = JsonStore("briefing.json")
# Pending outbound call: Jarvis called Sir about something important.
# {reason, created_at} — one at a time; the call consumes it.
call_request = JsonStore("call_request.json")
# People Sir told Jarvis never to DM until further notice:
# normalized name -> {name, blocked_at}. Checked before any DM reply
# (and before a missed-call introduction).
blocked_users = JsonStore("blocked_users.json")
# Recent Telegram conversation with Sir (last ~20 turns), so the brain
# can follow "it" / "that" / "today" in his next message. A list of
# {"role": "user"|"assistant", "content": ...} under key "messages".
# NEVER holds cookies, tokens or other secrets — those messages are
# consumed by the pending-connect handlers before recording.
telegram_history = JsonStore("telegram_history.json")
# Telegram webhook update_ids already handled (last ~200). Telegram
# retries a webhook when the first response is slow; without this the
# same update is processed twice and Sir gets duplicate replies.
seen_updates = JsonStore("telegram_updates.json")
# Which brain model Jarvis is using right now (set by /model). One key,
# "active": a model id from model_settings.MODELS. Turso-backed, so the
# choice survives redeploys. Default is "groq-120b".
model_settings = JsonStore("model_settings.json")
