# ====================================================================
# Phase 10 batch 4 tests: translate, podcast, notes_todo
# ====================================================================
from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools import get_registry, RiskTier


def test_phase10_batch4_plugins_register():
    reg = get_registry()
    reg.load_plugins([
        "plugins.translate.plugin",
        "plugins.podcast.plugin",
        "plugins.notes_todo.plugin",
    ])
    names = {t.name for t in reg.all_tools()}
    for required in [
        "translate.text", "translate.detect", "translate.languages",
        "podcast.list_episodes", "podcast.download", "podcast.transcribe",
        "notes.create", "notes.list", "notes.read", "notes.search",
        "todo.add", "todo.list", "todo.complete", "todo.delete",
    ]:
        assert required in names, f"{required} missing"


# --------------------------------------------------------------------
# Notes — full round-trip
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notes_create_then_list_then_read(monkeypatch, tmp_path):
    import plugins.notes_todo.plugin as nt
    monkeypatch.setattr(nt, "_notes_dir", lambda: tmp_path)

    create = await nt.notes_create(title="My Note", content="hello world", tags=["test"])
    assert create["ok"] is True

    listing = await nt.notes_list()
    assert listing["ok"] is True
    assert listing["count"] == 1

    # Find the actual filename.
    filename = listing["notes"][0]
    read = await nt.notes_read(filename=filename)
    assert read["ok"] is True
    assert "hello world" in read["content"]


@pytest.mark.asyncio
async def test_notes_search_finds_keywords(monkeypatch, tmp_path):
    import plugins.notes_todo.plugin as nt
    monkeypatch.setattr(nt, "_notes_dir", lambda: tmp_path)

    await nt.notes_create(title="Python Tips", content="use list comprehensions", tags=[])
    await nt.notes_create(title="Rust Notes", content="borrow checker is strict", tags=[])
    result = await nt.notes_search(query="python", max_results=10)
    assert result["ok"] is True
    assert result["count"] == 1
    assert "python" in result["matches"][0]["snippet"].lower()


# --------------------------------------------------------------------
# Todos — full round-trip with isolated SQLite DB
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_todo_add_list_complete_delete(monkeypatch, tmp_path):
    import plugins.notes_todo.plugin as nt
    db_path = tmp_path / "todos.db"
    monkeypatch.setattr(nt, "_TODOS_DB", db_path)

    add1 = await nt.todo_add(text="Write tests", priority="high")
    add2 = await nt.todo_add(text="Ship release", priority="critical")
    assert add1["ok"] is True
    assert add2["ok"] is True

    listing = await nt.todo_list()
    assert listing["count"] == 2

    complete = await nt.todo_complete(id=add1["id"])
    assert complete["ok"] is True

    # Default list excludes completed.
    after_complete = await nt.todo_list()
    assert after_complete["count"] == 1
    # Include completed gets both.
    all_todos = await nt.todo_list(include_completed=True)
    assert all_todos["count"] == 2

    deleted = await nt.todo_delete(id=add2["id"])
    assert deleted["ok"] is True
    final = await nt.todo_list(include_completed=True)
    assert final["count"] == 1


# --------------------------------------------------------------------
# Translate — graceful error on bad endpoint
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_translate_handles_bad_endpoint(monkeypatch):
    """If the LibreTranslate endpoint is unreachable, return ok=False cleanly."""
    import plugins.translate.plugin as tr
    monkeypatch.setattr(tr, "_base_url", lambda: "http://127.0.0.1:1")  # unreachable port
    result = await tr.translate_text(text="hello", target="es")
    assert result["ok"] is False


def test_translate_tools_are_tier_0():
    reg = get_registry()
    for t in reg.all_tools():
        if t.category == "translate":
            assert t.risk_tier is RiskTier.TIER_0_OBSERVE
