# ====================================================================
# JARVIS OMEGA — Obsidian Vault (permanent memory) tests
# ====================================================================
"""
Tests for the Obsidian vault (2026-11-11): a Markdown memory that
never deletes.

* Notes are created, edited and appended to; every edit keeps the
  previous body in a revision history, and there is no delete
  function, endpoint or cleanup anywhere in the module.
* The vault mirrors to Turso (table dm_obsidian_vault) like every
  dm_store, so it survives Render redeploys.
* Sir's standing rules live in the "Rules" note; the DM brain injects
  them into its system prompt, so a rule is followed, not just noted.
* /rule and /memory commands, plain-language rule detection
  ("from now on ...", "always ...", "never ..."), and /rules listing
  the vault rules alongside the auto-reply rules.

ALL credentials and endpoints here are FAKE. No real Turso database
is touched: the "server" is an in-memory fake behind
httpx.MockTransport speaking the Hrana /v2/pipeline shape.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.router_telegram import (
    _detect_rule,
    _handle_memory,
    _handle_remember,
    _handle_rule,
)
from backend.services import dm_store
from backend.services.dm_llm import _messages
from backend.services.dm_store import JsonStore
from backend.services.obsidian_vault import ObsidianVault, vault

_FAKE_URL = "libsql://fake-host.turso.io"
_FAKE_TOKEN = "fake-token"


class _FakeTurso:
    """In-memory stand-in for Turso's /v2/pipeline endpoint."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.calls = 0
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(500, json={"error": "boom"}, request=request)
        body = json.loads(request.content.decode())
        results = []
        for req in body.get("requests", []):
            if req.get("type") == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = req.get("stmt", {})
            sql = stmt.get("sql", "")
            args = [a.get("value") for a in stmt.get("args", [])]
            rows, affected = self._run(sql, args)
            results.append({
                "type": "ok",
                "response": {"type": "execute", "result": {
                    "cols": [{"name": "key"}, {"name": "value"}],
                    "rows": [[{"type": "text", "value": v} for v in row] for row in rows],
                    "affected_row_count": affected,
                }},
            })
        return httpx.Response(200, json={"results": results}, request=request)

    def _run(self, sql: str, args: list[str]) -> tuple[list[tuple], int]:
        if sql.startswith("CREATE TABLE"):
            return [], 0
        if sql.startswith("SELECT"):
            return [(k, v) for k, v in self.rows.items()], 0
        if sql.startswith("INSERT OR REPLACE"):
            self.rows[args[0]] = args[1]
            return [], 1
        if sql.startswith("DELETE FROM"):
            if "NOT IN" in sql:
                keep = set(args)
                removed = [k for k in self.rows if k not in keep]
                for k in removed:
                    del self.rows[k]
                return [], len(removed)
            n = len(self.rows)
            self.rows.clear()
            return [], n
        raise AssertionError(f"unexpected SQL in fake Turso: {sql!r}")


def _set_turso_env(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.config.settings.turso_database_url", _FAKE_URL
    )
    monkeypatch.setattr(
        "backend.config.settings.turso_auth_token", _FAKE_TOKEN
    )


def _reset_dm_store_turso(monkeypatch, fake) -> None:
    """Point dm_store's Turso mirror at the fake and clear its cache."""
    _set_turso_env(monkeypatch)
    monkeypatch.setattr(dm_store, "_test_turso_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(dm_store, "_turso_clients", {})
    monkeypatch.setattr(dm_store, "_turso_ensured", set())


def _use_tmp_vault(monkeypatch, tmp_path):
    monkeypatch.setattr(vault._store, "_path", tmp_path / "obsidian_vault.json")
    monkeypatch.setattr(vault._store, "_loaded", False)
    monkeypatch.setattr(vault._store, "_data", {})


# --------------------------------------------------------------------
# Notes: create / get / list / search
# --------------------------------------------------------------------

def test_vault_note_crud(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    note_id = vault.create_note("My Project", "hello **world**", tags=["Work"], source="test")
    assert note_id == "my-project"
    note = vault.get_note(note_id)
    assert note is not None
    assert note["title"] == "My Project"
    assert note["body"] == "hello **world**"
    assert note["tags"] == ["work"]
    assert vault.get_note_by_title("my project")["id"] == note_id
    assert vault.get_note("nope") is None
    assert vault.note_count() == 1
    summaries = vault.list_notes()
    assert [s["id"] for s in summaries] == [note_id]
    assert summaries[0]["preview"] == "hello **world**"
    assert [s["id"] for s in vault.list_notes(tag="work")] == [note_id]
    assert vault.list_notes(tag="other") == []
    matches = vault.search_notes("WORLD")
    assert [m["id"] for m in matches] == [note_id]
    assert vault.search_notes("zzz") == []
    # A title clash gets a suffix, never an overwrite.
    note_id2 = vault.create_note("My Project", "second", source="test")
    assert note_id2 == "my-project-2"
    assert vault.note_count() == 2


def test_vault_update_keeps_revision(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    note_id = vault.create_note("Draft", "version one", source="test")
    assert vault.update_note(note_id, "version two", edited_by="test") is True
    assert vault.get_note(note_id)["body"] == "version two"
    revisions = vault.revisions(note_id)
    assert len(revisions) == 1
    assert revisions[0]["body"] == "version one"
    assert revisions[0]["edited_by"] == "test"
    # A no-op update adds no revision.
    assert vault.update_note(note_id, "version two") is True
    assert len(vault.revisions(note_id)) == 1
    assert vault.update_note("missing", "x") is False


def test_vault_append(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    note_id = vault.create_note("Log", "first line", source="test")
    assert vault.append_to_note(note_id, "second line") is True
    assert vault.get_note(note_id)["body"] == "first line\nsecond line"
    assert len(vault.revisions(note_id)) == 1  # old body kept
    assert vault.append_to_note("missing", "x") is False
    assert vault.append_to_note(note_id, "  ") is False


# --------------------------------------------------------------------
# Rules + facts
# --------------------------------------------------------------------

def test_vault_rules(monkeypatch, tmp_path):
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    _use_tmp_vault(monkeypatch, tmp_path)
    assert vault.list_rules() == [STANDING_RULE_NEVER_INVENT]
    assert vault.rules_text() == f"- {STANDING_RULE_NEVER_INVENT}"
    assert vault.add_rule("always answer in Arabic", source="test") == "always answer in Arabic"
    assert vault.add_rule("never DM Omar", source="test") == "never DM Omar"
    assert vault.list_rules() == [
        STANDING_RULE_NEVER_INVENT,
        "always answer in Arabic",
        "never DM Omar",
    ]
    assert vault.rules_text() == (
        f"- {STANDING_RULE_NEVER_INVENT}\n"
        "- always answer in Arabic\n- never DM Omar"
    )
    # An exact duplicate is not added twice.
    assert vault.add_rule("always answer in Arabic", source="test") == "always answer in Arabic"
    assert vault.list_rules() == [
        STANDING_RULE_NEVER_INVENT,
        "always answer in Arabic",
        "never DM Omar",
    ]
    assert vault.add_rule("   ") is None
    assert vault.add_rule("") is None


def test_vault_facts(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    assert vault.remember_fact("Omar loves football", source="test") == "Omar loves football"
    facts = vault.get_note("facts")
    assert facts is not None
    assert "Omar loves football" in facts["body"]
    assert vault.remember_fact("   ") is None


def test_vault_never_deletes():
    """The guarantee, locked in: there is no delete on the vault."""
    assert not hasattr(vault, "delete_note")
    assert not hasattr(vault, "delete_revision")
    assert not hasattr(vault, "clear")
    assert not hasattr(ObsidianVault, "delete_note")
    assert not hasattr(ObsidianVault, "delete_revision")
    import backend.services.obsidian_vault as module

    with open(module.__file__, encoding="utf-8") as fh:
        assert "def delete" not in fh.read()


# --------------------------------------------------------------------
# Turso mirror: survives a deploy (local file wiped, Turso restores)
# --------------------------------------------------------------------

def test_vault_turso_mirror_and_restore(monkeypatch, tmp_path):
    fake = _FakeTurso()
    _reset_dm_store_turso(monkeypatch, fake)
    _use_tmp_vault(monkeypatch, tmp_path)
    vault.add_rule("always answer in Arabic", source="test")
    vault.create_note("Keep Me", "permanent", source="test")
    assert "vault" in fake.rows
    saved = json.loads(fake.rows["vault"])
    assert "always answer in Arabic" in saved["notes"]["rules"]["body"]
    assert "Keep Me" in saved["notes"]["keep-me"]["title"]
    # Fresh deploy: local file gone, Turso restores the whole vault.
    fresh_store = JsonStore("obsidian_vault.json")
    fresh_store._path = tmp_path / "fresh.json"  # does not exist
    fresh = ObsidianVault(store=fresh_store)
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    assert fresh.list_rules() == [
        STANDING_RULE_NEVER_INVENT,
        "always answer in Arabic",
    ]
    assert fresh.get_note("keep-me")["body"] == "permanent"


# --------------------------------------------------------------------
# Rule detection in plain words
# --------------------------------------------------------------------

def test_detect_rule_patterns():
    assert _detect_rule("from now on, always answer in Arabic") == "always answer in Arabic"
    assert _detect_rule("From now on never DM Omar") == "never DM Omar"
    assert _detect_rule("make it a rule that you call me sir") == "you call me sir"
    assert _detect_rule("as a rule, answer in Arabic") == "answer in Arabic"
    assert _detect_rule("always answer in Arabic") == "answer in Arabic"
    assert _detect_rule("never DM Omar again") == "DM Omar again"
    assert _detect_rule("من الآن فصاعداً أجب بالعربية دائماً") == "أجب بالعربية دائماً"
    assert _detect_rule("دائماً أجب بالعربية") == "أجب بالعربية"
    assert _detect_rule("أبداً لا تراسل عمر") == "لا تراسل عمر"
    # Not rules.
    assert _detect_rule("never mind") is None  # one word after "never"
    assert _detect_rule("hello") is None
    assert _detect_rule("") is None
    assert _detect_rule("remind me to call Omar at 5pm") is None


# --------------------------------------------------------------------
# The brain follows the rules: DM prompt injection
# --------------------------------------------------------------------

def test_dm_prompt_includes_vault_rules(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    vault.add_rule("always answer in Arabic", source="test")
    messages = _messages("Omar", "hello", first_reply=True)
    system = messages[0]["content"]
    assert "always answer in Arabic" in system
    assert "permanent memory" in system


# --------------------------------------------------------------------
# Telegram: /rule, /memory, plain rule sentences, /rules
# --------------------------------------------------------------------

def _telegram_app():
    from backend.routers.router_telegram import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def _webhook_post(text, update_id=1):
    return _telegram_app().post("/api/telegram/webhook", json={
        "update_id": update_id,
        "message": {"chat": {"id": 111}, "text": text},
    })


def _prep_webhook(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.config.settings.telegram_chat_id", "111")
    monkeypatch.setattr(dm_store.seen_updates, "_path", tmp_path / "telegram_updates.json")
    monkeypatch.setattr(dm_store.seen_updates, "_loaded", False)
    monkeypatch.setattr(dm_store.seen_updates, "_data", {})
    _use_tmp_vault(monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_webhook_rule_command(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/rule always answer in Arabic", update_id=21)
    assert resp.status_code == 200
    assert "always answer in Arabic" in mock_send.call_args.args[0]
    assert "permanent memory" in mock_send.call_args.args[0]
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    assert vault.list_rules() == [
        STANDING_RULE_NEVER_INVENT,
        "always answer in Arabic",
    ]
    # The new commands are registered in the menu.
    from backend.services.telegram_notifier import TELEGRAM_COMMANDS

    names = [c["command"] for c in TELEGRAM_COMMANDS]
    assert "rule" in names
    assert "memory" in names


@pytest.mark.asyncio
async def test_webhook_memory_command(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    vault.create_note("Trip Plan", "visit Aqaba in December", source="test")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/memory Aqaba", update_id=22)
    assert resp.status_code == 200
    assert "Trip Plan" in mock_send.call_args.args[0]
    assert "Aqaba" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_plain_rule_sentence(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("from now on, always answer in Arabic", update_id=23)
    assert resp.status_code == 200
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    assert vault.list_rules() == [
        STANDING_RULE_NEVER_INVENT,
        "always answer in Arabic",
    ]
    assert "permanent memory" in mock_send.call_args.args[0]


@pytest.mark.asyncio
async def test_webhook_rules_lists_vault_rules(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    monkeypatch.setattr(dm_store.rules, "_path", tmp_path / "dm_rules.json")
    monkeypatch.setattr(dm_store.rules, "_loaded", False)
    monkeypatch.setattr(dm_store.rules, "_data", {})
    vault.add_rule("always answer in Arabic", source="test")
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("list my rules", update_id=24)
    assert resp.status_code == 200
    sent = mock_send.call_args.args[0]
    assert "Standing rules (permanent memory)" in sent
    assert "always answer in Arabic" in sent


def test_handle_rule_and_memory_helpers(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    assert "empty" in _handle_memory("")
    assert "Usage" in _handle_rule("")
    assert "always answer" in _handle_rule("always answer in Arabic")
    vault.create_note("Trip Plan", "visit Aqaba", source="test")
    assert "Trip Plan" in _handle_memory("")
    assert "Aqaba" in _handle_memory("aqaba")
    assert "Nothing" in _handle_memory("zzz")


def test_remember_also_saves_fact_to_vault(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(dm_store.contacts, "_path", tmp_path / "contacts.json")
    monkeypatch.setattr(dm_store.contacts, "_loaded", False)
    monkeypatch.setattr(dm_store.contacts, "_data", {})
    reply = _handle_remember("Omar loves football")
    assert "Omar" in reply
    facts = vault.get_note("facts")
    assert facts is not None
    assert "Omar loves football" in facts["body"]


# --------------------------------------------------------------------
# Lessons: mistakes not to repeat
# --------------------------------------------------------------------

def test_vault_lessons(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    assert vault.list_lessons() == []
    assert vault.lessons_text() == ""
    assert vault.add_lesson("you should have asked me first", source="test") == (
        "you should have asked me first"
    )
    assert vault.add_lesson("don't send the summary before I approve it", source="test")
    assert vault.list_lessons() == [
        "you should have asked me first",
        "don't send the summary before I approve it",
    ]
    assert vault.lessons_text() == (
        "- you should have asked me first\n"
        "- don't send the summary before I approve it"
    )
    # An exact duplicate is not added twice.
    vault.add_lesson("you should have asked me first", source="test")
    assert len(vault.list_lessons()) == 2
    assert vault.add_lesson("   ") is None
    assert vault.add_lesson("") is None


def test_detect_lesson_patterns():
    from backend.routers.router_telegram import _detect_lesson

    assert _detect_lesson("you should have asked me first") == "you should have asked me first"
    assert _detect_lesson("that's wrong, the meeting is Friday") == "that's wrong, the meeting is Friday"
    assert _detect_lesson("you got it wrong") == "you got it wrong"
    assert _detect_lesson("don't do that again") == "don't do that again"
    assert _detect_lesson("next time ask me first") == "next time ask me first"
    assert _detect_lesson("you made a mistake, the price is 12 not 20") == "you made a mistake, the price is 12 not 20"
    assert _detect_lesson("هذا خطأ، السعر 12 وليس 20") == "هذا خطأ، السعر 12 وليس 20"
    assert _detect_lesson("كان يجب أن تسألني أولاً") == "كان يجب أن تسألني أولاً"
    assert _detect_lesson("المرة القادمة اسألني أولاً") == "المرة القادمة اسألني أولاً"
    # Not lessons.
    assert _detect_lesson("never mind") is None
    assert _detect_lesson("hello") is None
    assert _detect_lesson("wrong") is None  # one word
    assert _detect_lesson("") is None
    assert _detect_lesson("remind me to call Omar at 5pm") is None
    assert _detect_lesson("see you next time") is None


def test_dm_prompt_includes_vault_lessons(monkeypatch, tmp_path):
    _use_tmp_vault(monkeypatch, tmp_path)
    vault.add_lesson("you should have asked me first", source="test")
    messages = _messages("Omar", "hello", first_reply=True)
    system = messages[0]["content"]
    assert "you should have asked me first" in system
    assert "Lessons learned" in system


@pytest.mark.asyncio
async def test_webhook_lesson_command(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("/lesson don't send the summary before I approve it", update_id=31)
    assert resp.status_code == 200
    assert "don't send the summary" in mock_send.call_args.args[0]
    assert "permanent memory" in mock_send.call_args.args[0]
    assert vault.list_lessons() == ["don't send the summary before I approve it"]
    from backend.services.telegram_notifier import TELEGRAM_COMMANDS

    names = [c["command"] for c in TELEGRAM_COMMANDS]
    assert "lesson" in names


@pytest.mark.asyncio
async def test_webhook_plain_correction(monkeypatch, tmp_path):
    _prep_webhook(monkeypatch, tmp_path)
    fake_responder = MagicMock()
    fake_responder.get_pending_draft.return_value = None
    with (
        patch("backend.routers.router_telegram.send_telegram_message",
              new=AsyncMock(return_value=True)) as mock_send,
        patch("backend.services.dm_responder.dm_responder", fake_responder),
    ):
        resp = _webhook_post("you should have asked me first", update_id=32)
    assert resp.status_code == 200
    assert vault.list_lessons() == ["you should have asked me first"]
    assert "Lesson learned" in mock_send.call_args.args[0]


# --------------------------------------------------------------------
# Standing rule: never invent anything (2026-11-11)
# --------------------------------------------------------------------

def test_standing_rule_always_first(monkeypatch, tmp_path):
    """The never-invent rule is first even in an empty vault."""
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    _use_tmp_vault(monkeypatch, tmp_path)
    assert vault.list_rules() == [STANDING_RULE_NEVER_INVENT]
    assert "Never invent anything" in vault.rules_text()
    vault.add_rule("always answer in Arabic", source="test")
    rules = vault.list_rules()
    assert rules[0] == STANDING_RULE_NEVER_INVENT
    assert rules[1] == "always answer in Arabic"


def test_standing_rule_not_duplicated(monkeypatch, tmp_path):
    """Adding the same rule by hand does not duplicate it."""
    from backend.services.obsidian_vault import STANDING_RULE_NEVER_INVENT

    _use_tmp_vault(monkeypatch, tmp_path)
    vault.add_rule(STANDING_RULE_NEVER_INVENT, source="test")
    assert vault.list_rules().count(STANDING_RULE_NEVER_INVENT) == 1


def test_dm_prompt_includes_never_invent(monkeypatch, tmp_path):
    """The DM brain is told never to invent, even with no other rules."""
    _use_tmp_vault(monkeypatch, tmp_path)
    messages = _messages("Omar", "hello", first_reply=True)
    system = messages[0]["content"]
    assert "NEVER INVENT ANYTHING" in system
    assert "Never invent anything" in system


def test_telegram_system_includes_never_invent():
    """The Telegram chat prompt carries the never-invent rule."""
    from backend.routers.router_telegram import _TELEGRAM_SYSTEM

    assert "NEVER INVENT ANYTHING" in _TELEGRAM_SYSTEM
    assert "say you do not know" in _TELEGRAM_SYSTEM


def test_llm_service_prompt_includes_never_invent():
    """The general chat brain prompt carries the never-invent rule
    (injected from the vault's standing rules)."""
    from backend.services.llm_service import llm_service

    prompt = llm_service._build_default_system_prompt()
    assert "Never invent anything" in prompt
    assert "say you do not know" in prompt
