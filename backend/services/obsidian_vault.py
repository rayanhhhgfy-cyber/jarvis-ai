# ====================================================================
# JARVIS OMEGA — Obsidian Vault (permanent memory)
# ====================================================================
"""
Obsidian-style permanent memory for Jarvis.

A vault of Markdown notes that NEVER deletes: there is no delete
function, no delete endpoint and no consolidation cleanup anywhere
in this module. Notes can be created and edited, and every edit
appends the previous body to a revision history first, so even the
old text is never lost. The vault only grows.

Storage is the same proven pattern as dm_store: a local JSON file
(./storage/obsidian_vault.json) mirrored to Turso (table
``dm_obsidian_vault``), so the vault survives Render redeploys, which
wipe local disk. The local file is trusted when it exists; Turso
restores it when the file is missing.

The agent (Jarvis) can read and edit the vault freely through this
module. Sir's standing rules live in the "Rules" note; the DM brain
and the chat brain both inject those rules into their system prompts,
so a rule Sir states is actually followed. When Sir tells Jarvis a
rule in plain words ("from now on ...", "always ...", "never ..."),
the Telegram router saves it here automatically.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.services.dm_store import JsonStore
from shared.logger import get_logger

log = get_logger("obsidian_vault")

_RULES_NOTE_ID = "rules"
_RULES_NOTE_TITLE = "Rules"
_FACTS_NOTE_ID = "facts"
_FACTS_NOTE_TITLE = "Facts"
_MAX_RULES_CHARS = 2000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "note-" + uuid.uuid4().hex[:8]
    return slug


class ObsidianVault:
    """A vault of Markdown notes that never deletes.

    There is deliberately no delete method on this class. Notes are
    created, edited and appended to; every edit keeps the previous
    body in the revision history, so nothing is ever lost.
    """

    def __init__(self, store: JsonStore | None = None) -> None:
        self._store = store or JsonStore("obsidian_vault.json")

    # -- storage ---------------------------------------------------

    def _load_vault(self) -> dict[str, Any]:
        data = self._store.all()
        vault = data.get("vault")
        if not isinstance(vault, dict):
            vault = {"notes": {}, "revisions": {}}
        if not isinstance(vault.get("notes"), dict):
            vault["notes"] = {}
        if not isinstance(vault.get("revisions"), dict):
            vault["revisions"] = {}
        return vault

    def _save_vault(self, vault: dict[str, Any]) -> None:
        self._store.set("vault", vault)

    def _ensure_note(
        self,
        vault: dict[str, Any],
        note_id: str,
        title: str,
        tags: list[str],
        source: str,
    ) -> dict[str, Any]:
        note = vault["notes"].get(note_id)
        if note is None:
            now = _now_iso()
            note = {
                "title": title,
                "body": "",
                "tags": sorted(set(tags)),
                "created_at": now,
                "updated_at": now,
                "source": source,
            }
            vault["notes"][note_id] = note
            vault["revisions"].setdefault(note_id, [])
        return note

    def _append_line(
        self,
        vault: dict[str, Any],
        note_id: str,
        title: str,
        tags: list[str],
        line: str,
        source: str,
    ) -> bool:
        """Append one Markdown line to a note (dedupe exact repeats)."""
        line = (line or "").strip()
        if not line:
            return False
        note = self._ensure_note(vault, note_id, title, tags, source)
        body = (note.get("body") or "").rstrip()
        existing = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if line in existing:
            return True
        vault["revisions"].setdefault(note_id, []).append(
            {"body": body, "edited_at": _now_iso(), "edited_by": source}
        )
        note["body"] = f"{body}\n{line}".strip() if body else line
        note["updated_at"] = _now_iso()
        self._save_vault(vault)
        return True

    # -- notes -----------------------------------------------------

    def create_note(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        source: str = "api",
    ) -> str:
        """Create a note; returns its id. A title clash gets -2, -3..."""
        title = (title or "").strip() or "Untitled"
        body = (body or "").strip()
        vault = self._load_vault()
        notes = vault["notes"]
        note_id = _slug(title)
        base = note_id
        n = 2
        while note_id in notes:
            note_id = f"{base}-{n}"
            n += 1
        now = _now_iso()
        notes[note_id] = {
            "title": title,
            "body": body,
            "tags": sorted({t.strip().lower() for t in (tags or []) if t.strip()}),
            "created_at": now,
            "updated_at": now,
            "source": source,
        }
        vault["revisions"].setdefault(note_id, [])
        self._save_vault(vault)
        log.info("obsidian_note_created", note_id=note_id, title=title)
        return note_id

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        vault = self._load_vault()
        note = vault["notes"].get(note_id)
        if note is None:
            return None
        return {"id": note_id, **note}

    def get_note_by_title(self, title: str) -> dict[str, Any] | None:
        title = (title or "").strip().lower()
        if not title:
            return None
        vault = self._load_vault()
        for note_id, note in vault["notes"].items():
            if (note.get("title") or "").strip().lower() == title:
                return {"id": note_id, **note}
        return None

    def update_note(
        self, note_id: str, new_body: str, edited_by: str = "jarvis"
    ) -> bool:
        """Replace a note's body; the old body is kept as a revision."""
        vault = self._load_vault()
        note = vault["notes"].get(note_id)
        if note is None:
            return False
        new_body = (new_body or "").strip()
        if new_body == (note.get("body") or ""):
            return True
        vault["revisions"].setdefault(note_id, []).append(
            {
                "body": note.get("body") or "",
                "edited_at": _now_iso(),
                "edited_by": edited_by,
            }
        )
        note["body"] = new_body
        note["updated_at"] = _now_iso()
        self._save_vault(vault)
        log.info("obsidian_note_updated", note_id=note_id)
        return True

    def append_to_note(
        self, note_id: str, text: str, edited_by: str = "jarvis"
    ) -> bool:
        """Append text to a note; the previous body is kept as a revision."""
        text = (text or "").strip()
        if not text:
            return False
        vault = self._load_vault()
        note = vault["notes"].get(note_id)
        if note is None:
            return False
        body = (note.get("body") or "").rstrip()
        vault["revisions"].setdefault(note_id, []).append(
            {"body": body, "edited_at": _now_iso(), "edited_by": edited_by}
        )
        note["body"] = f"{body}\n{text}".strip() if body else text
        note["updated_at"] = _now_iso()
        self._save_vault(vault)
        return True

    def revisions(self, note_id: str) -> list[dict[str, Any]]:
        """Every previous body of a note, oldest first. Never emptied."""
        vault = self._load_vault()
        return list(vault["revisions"].get(note_id, []))

    def list_notes(self, tag: str | None = None) -> list[dict[str, Any]]:
        """Note summaries, newest first. Filter by tag when given."""
        vault = self._load_vault()
        out: list[dict[str, Any]] = []
        for note_id, note in vault["notes"].items():
            tags = note.get("tags") or []
            if tag and tag.lower() not in [t.lower() for t in tags]:
                continue
            body = note.get("body") or ""
            out.append(
                {
                    "id": note_id,
                    "title": note.get("title", ""),
                    "tags": tags,
                    "updated_at": note.get("updated_at", ""),
                    "preview": body[:120],
                }
            )
        out.sort(key=lambda n: n["updated_at"], reverse=True)
        return out

    def search_notes(self, query: str) -> list[dict[str, Any]]:
        """Case-insensitive substring search over title, body and tags."""
        q = (query or "").strip().lower()
        if not q:
            return self.list_notes()
        vault = self._load_vault()
        out: list[dict[str, Any]] = []
        for note_id, note in vault["notes"].items():
            title = note.get("title", "")
            body = note.get("body") or ""
            tags = note.get("tags") or []
            hay = f"{title}\n{body}\n{' '.join(tags)}".lower()
            if q not in hay:
                continue
            snippet = body[:120]
            for line in body.splitlines():
                if q in line.lower():
                    snippet = line.strip()[:160]
                    break
            out.append(
                {"id": note_id, "title": title, "tags": tags, "snippet": snippet}
            )
        return out

    def note_count(self) -> int:
        return len(self._load_vault()["notes"])

    # -- rules -----------------------------------------------------

    def add_rule(self, text: str, source: str = "telegram") -> str | None:
        """Save a standing rule to the Rules note. Returns it, or None."""
        text = (text or "").strip()
        if not text:
            return None
        vault = self._load_vault()
        ok = self._append_line(
            vault, _RULES_NOTE_ID, _RULES_NOTE_TITLE, ["rule"], f"- {text}", source
        )
        if ok:
            log.info("obsidian_rule_added", rule=text)
            return text
        return None

    def list_rules(self) -> list[str]:
        """Every standing rule, in the order Sir stated them."""
        note = self.get_note(_RULES_NOTE_ID)
        if note is None:
            return []
        rules: list[str] = []
        for line in (note.get("body") or "").splitlines():
            line = line.strip()
            if line.startswith("- "):
                rules.append(line[2:].strip())
            elif line:
                rules.append(line)
        return rules

    def rules_text(self, max_chars: int = _MAX_RULES_CHARS) -> str:
        """Rules as a Markdown list, ready to inject into a prompt."""
        rules = self.list_rules()
        if not rules:
            return ""
        return "\n".join(f"- {r}" for r in rules)[:max_chars]

    # -- facts -----------------------------------------------------

    def remember_fact(self, text: str, source: str = "telegram") -> str | None:
        """Save a durable fact to the Facts note. Returns it, or None."""
        text = (text or "").strip()
        if not text:
            return None
        vault = self._load_vault()
        ok = self._append_line(
            vault, _FACTS_NOTE_ID, _FACTS_NOTE_TITLE, ["fact"], f"- {text}", source
        )
        if ok:
            log.info("obsidian_fact_added", fact=text)
            return text
        return None


# One vault for the whole backend. The JsonStore underneath mirrors to
# Turso, so the vault survives redeploys; the local file is the cache.
vault = ObsidianVault()
