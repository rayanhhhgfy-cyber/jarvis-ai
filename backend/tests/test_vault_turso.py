# ====================================================================
# JARVIS OMEGA — Turso-backed vault tests
# ====================================================================
"""
Tests for the connector vault's Turso backing (Render redeploy survival).

ALL credentials here are FAKE. No real Turso database is touched: the
"server" is an in-memory fake behind httpx.MockTransport that speaks
the same Hrana /v2/pipeline shape the vault client sends. A "stored"
value in the fake is the vault's Fernet-encrypted entry blob — the
tests assert the fake never sees the plaintext.
"""

from __future__ import annotations

import json

import httpx

from backend.services.credentials_vault import CredentialsVault

_FAKE_URL = "libsql://fake-host.turso.io"
_FAKE_TOKEN = "fake-turso-token"


class _FakeTurso:
    """In-memory stand-in for Turso's /v2/pipeline endpoint."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.calls = 0
        self.fail = False  # when True, every request returns HTTP 500

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
        "backend.services.credentials_vault.settings.turso_database_url", _FAKE_URL
    )
    monkeypatch.setattr(
        "backend.services.credentials_vault.settings.turso_auth_token", _FAKE_TOKEN
    )


def _vault(tmp_path, fake, table="vault_entries", name="vault.json"):
    return CredentialsVault(
        storage_path=str(tmp_path / name),
        turso_table=table,
        turso_transport=httpx.MockTransport(fake.handler),
    )


def test_vault_round_trips_via_turso(tmp_path, monkeypatch):
    """set() lands in Turso (ciphertext only); a fresh vault loads it back."""
    _set_turso_env(monkeypatch)
    fake = _FakeTurso()
    vault = _vault(tmp_path, fake)
    vault.initialize()
    vault.set("connector_instagram", "fake-secret-value", category="connector")

    assert "connector_instagram" in fake.rows
    assert "fake-secret-value" not in fake.rows["connector_instagram"]

    # A fresh vault with an empty local file loads the value from Turso.
    vault2 = _vault(tmp_path, fake, name="vault2.json")
    vault2.initialize()
    assert vault2.get("connector_instagram") == "fake-secret-value"
    # ...and the local cache file was refreshed from Turso.
    assert (tmp_path / "vault2.json").exists()


def test_vault_falls_back_to_local_when_turso_down(tmp_path, monkeypatch):
    """Turso 500s: the vault keeps working off the local file, no crash."""
    _set_turso_env(monkeypatch)
    fake = _FakeTurso()
    fake.fail = True
    vault = _vault(tmp_path, fake)
    vault.initialize()  # must not raise
    vault.set("connector_messenger", "fake-secret-value", category="connector")
    assert vault.get("connector_messenger") == "fake-secret-value"
    blob = json.loads((tmp_path / "vault.json").read_text(encoding="utf-8"))
    assert "connector_messenger" in blob["entries"]


def test_vault_local_only_when_env_unset(tmp_path):
    """No TURSO_* env vars: the transport is never touched, file only."""
    fake = _FakeTurso()
    vault = _vault(tmp_path, fake)
    vault.initialize()
    vault.set("connector_instagram", "fake-secret-value", category="connector")
    assert vault.get("connector_instagram") == "fake-secret-value"
    assert fake.calls == 0
    blob = json.loads((tmp_path / "vault.json").read_text(encoding="utf-8"))
    assert "connector_instagram" in blob["entries"]


def test_vault_migrates_local_entries_to_turso(tmp_path, monkeypatch):
    """Local file has entries, Turso empty: first init pushes them up."""
    # Local-only run first (no env vars): entries land in the file only.
    fake = _FakeTurso()
    local_vault = _vault(tmp_path, fake, table=None)
    local_vault.initialize()
    local_vault.set("connector_instagram", "fake-secret-value", category="connector")
    assert fake.rows == {}

    # Now Turso is configured: init loads the local entry and migrates it.
    _set_turso_env(monkeypatch)
    vault = _vault(tmp_path, fake)
    vault.initialize()
    assert vault.get("connector_instagram") == "fake-secret-value"
    assert "connector_instagram" in fake.rows
    assert "fake-secret-value" not in fake.rows["connector_instagram"]


def test_vault_delete_removes_turso_row(tmp_path, monkeypatch):
    _set_turso_env(monkeypatch)
    fake = _FakeTurso()
    vault = _vault(tmp_path, fake)
    vault.initialize()
    vault.set("connector_instagram", "fake-secret-1", category="connector")
    vault.set("connector_messenger", "fake-secret-2", category="connector")
    assert len(fake.rows) == 2
    assert vault.delete("connector_instagram") is True
    assert "connector_instagram" not in fake.rows
    assert "connector_messenger" in fake.rows
    assert vault.get("connector_instagram") is None
    assert vault.get("connector_messenger") == "fake-secret-2"


def test_vault_bad_turso_url_falls_back_to_local(tmp_path, monkeypatch):
    """A malformed TURSO_DATABASE_URL must not break the vault."""
    monkeypatch.setattr(
        "backend.services.credentials_vault.settings.turso_database_url",
        "not-a-libsql-url",
    )
    monkeypatch.setattr(
        "backend.services.credentials_vault.settings.turso_auth_token", _FAKE_TOKEN
    )
    fake = _FakeTurso()
    vault = _vault(tmp_path, fake)
    vault.initialize()  # must not raise
    vault.set("connector_instagram", "fake-secret-value", category="connector")
    assert vault.get("connector_instagram") == "fake-secret-value"
    assert fake.calls == 0
