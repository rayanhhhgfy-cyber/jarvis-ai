# ====================================================================
# JARVIS OMEGA — Credentials Vault
# ====================================================================
"""
Phase 8 encrypted store for plugin credentials.

Plugins never read API keys from ``.env`` directly. They call
``credentials_vault.get(key)``. The vault persists encrypted (Fernet) at
``storage/credentials.json`` using the same ``ENCRYPTION_KEY`` that
bootstraps the security module.

Write access goes through ``set()`` (called by the Settings router).
Read access is also via ``get()``, but the REST API NEVER returns plaintext
— it only returns a masked preview (first 4 + last 4 chars).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet

from backend.config import settings
from shared.logger import get_logger

log = get_logger("credentials_vault")


class _TursoStore:
    """Minimal sync Turso client over the Hrana ``/v2/pipeline`` HTTP API.

    Same shape as the pure-Python client in future-thinkers'
    ``backend/db_turso.py`` (proven against Turso in production): one POST
    carrying a list of ``execute`` requests plus a ``close``, with Hrana
    typed args (``{"type": "text", "value": ...}``) and rows decoded back
    from the same shape.

    Only the surface the vault needs: ensure the table, load all rows,
    save all rows. Values stored here are the vault's already
    Fernet-encrypted entry blobs, so Turso only ever sees ciphertext —
    never a plaintext credential.
    """

    def __init__(
        self,
        database_url: str,
        auth_token: str,
        table: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if database_url.startswith("libsql://"):
            host = database_url[len("libsql://"):].split("/")[0]
        elif database_url.startswith("https://"):
            host = database_url[len("https://"):].split("/")[0]
        else:
            raise ValueError(
                "TURSO_DATABASE_URL must start with libsql:// or https://"
            )
        if not host:
            raise ValueError("TURSO_DATABASE_URL has no host")
        self._url = f"https://{host}/v2/pipeline"
        self._token = auth_token
        self._table = table.replace('"', '""')
        self._transport = transport

    # -- Hrana value codec (text only is all the vault needs) --

    @staticmethod
    def _arg(value: str) -> dict[str, str]:
        return {"type": "text", "value": str(value)}

    @staticmethod
    def _val(v: dict[str, Any]) -> Any:
        val_type = v.get("type")
        val = v.get("value")
        if val_type == "null":
            return None
        if val_type == "integer":
            try:
                return int(val)
            except (TypeError, ValueError):
                return val
        if val_type == "float":
            try:
                return float(val)
            except (TypeError, ValueError):
                return val
        return val

    def _pipeline(self, statements: list[tuple[str, list[str]]]) -> list[list[tuple]]:
        """Run several statements in one pipeline POST; one row-list per statement."""
        requests = [
            {"type": "execute", "stmt": {"sql": sql, "args": [self._arg(a) for a in args]}}
            for sql, args in statements
        ]
        requests.append({"type": "close"})
        try:
            with httpx.Client(transport=self._transport, timeout=25.0) as client:
                resp = client.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                    },
                    json={"requests": requests},
                )
        except httpx.HTTPError as e:
            raise RuntimeError(f"Turso request failed: {e}") from e
        if resp.status_code != 200:
            raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as e:
            raise RuntimeError(f"Turso returned non-JSON: {resp.text[:200]}") from e
        results = body.get("results") or []
        if len(results) < len(statements):
            raise RuntimeError(f"Turso: short response: {str(body)[:200]}")
        out: list[list[tuple]] = []
        for result in results[: len(statements)]:
            if result.get("type") == "error":
                err = result.get("error", {})
                raise RuntimeError(f"Turso SQL error: {err.get('message', err)}")
            rows = result.get("response", {}).get("result", {}).get("rows", [])
            out.append([tuple(self._val(v) for v in row) for row in rows])
        return out

    # -- Vault operations --

    def ensure_table(self) -> None:
        sql = (
            f'CREATE TABLE IF NOT EXISTS "{self._table}" '
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        self._pipeline([(sql, [])])

    def load_all(self) -> dict[str, dict[str, str]]:
        rows = self._pipeline([(
            f'SELECT key, value FROM "{self._table}"',
            [],
        )])[0]
        entries: dict[str, dict[str, str]] = {}
        for key, value in rows:
            try:
                entries[str(key)] = json.loads(value)
            except (TypeError, ValueError):
                log.warning("turso_vault_bad_row", key=str(key))
        return entries

    def save_all(self, entries: dict[str, dict[str, str]]) -> None:
        statements: list[tuple[str, list[str]]] = [
            (
                f'INSERT OR REPLACE INTO "{self._table}" (key, value) VALUES (?, ?)',
                [key, json.dumps(entry)],
            )
            for key, entry in entries.items()
        ]
        if entries:
            placeholders = ",".join("?" * len(entries))
            statements.append((
                f'DELETE FROM "{self._table}" WHERE key NOT IN ({placeholders})',
                list(entries.keys()),
            ))
        else:
            statements.append((f'DELETE FROM "{self._table}"', []))
        self._pipeline(statements)


class CredentialsVault:
    """
    Encrypted JSON key/value store for plugin credentials.

    Layout on disk (``storage/credentials.json``)::

        {
          "version": 1,
          "entries": {
            "openrouter_api_key":   {"ciphertext": "...", "category": "llm"},
            "aws_access_key_id":    {"ciphertext": "...", "category": "cloud"},
            ...
          }
        }
    """

    def __init__(
        self,
        storage_path: str | None = None,
        turso_table: str | None = None,
        turso_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._path = Path(storage_path or "./storage/credentials.json")
        self._entries: Dict[str, Dict[str, str]] = {}
        self._fernet: Fernet | None = None
        # Optional Turso backing: only vaults constructed with a table name
        # use it (the connector vault does; the plugin-credentials vault
        # stays local-only). The local file remains the cache either way.
        self._turso_table = turso_table
        self._turso_transport = turso_transport
        self._turso: _TursoStore | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Load the encrypted file and prepare the Fernet cipher."""
        # Reuse the security module's Fernet instance so we share the same key.
        from shared.security import _fernet as sec_fernet
        if sec_fernet is None:
            raise RuntimeError(
                "shared.security must be initialized before credentials_vault"
            )
        self._fernet = sec_fernet
        self._turso = self._maybe_init_turso()
        # Turso first when configured: it survives redeploys, the local
        # file does not. Any Turso failure falls back to the local file.
        if self._turso is not None:
            try:
                self._turso.ensure_table()
                turso_entries = self._turso.load_all()
            except RuntimeError as e:
                log.warning("turso_vault_unavailable", error=str(e))
                turso_entries = None
            if turso_entries:
                self._entries = turso_entries
                log.info("credentials_loaded_turso", count=len(self._entries))
                self._persist_local()
                return
            if turso_entries is not None:
                # Turso reachable but empty: keep whatever the local file
                # has, and push it up so it survives the next redeploy.
                self._load_local()
                if self._entries:
                    self._persist_turso()
                return
        self._load_local()

    def _maybe_init_turso(self) -> _TursoStore | None:
        """Build the Turso store when this vault opts in AND env is set."""
        if not self._turso_table:
            return None
        url = settings.turso_database_url
        token = settings.turso_auth_token
        if not url or not token:
            return None
        try:
            return _TursoStore(url, token, self._turso_table, transport=self._turso_transport)
        except ValueError as e:
            log.warning("turso_vault_bad_config", error=str(e))
            return None

    def _load_local(self) -> None:
        if self._path.exists():
            try:
                blob = json.loads(self._path.read_text(encoding="utf-8"))
                self._entries = blob.get("entries", {})
                log.info("credentials_loaded", count=len(self._entries))
            except Exception as e:
                log.error("credentials_load_failed", error=str(e))
                self._entries = {}
        else:
            self._entries = {}

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """Decrypt and return the value for ``key`` (or None if not set)."""
        entry = self._entries.get(key)
        if not entry:
            return None
        try:
            assert self._fernet is not None
            return self._fernet.decrypt(entry["ciphertext"].encode()).decode()
        except Exception as e:
            log.error("credentials_decrypt_failed", key=key, error=str(e))
            return None

    def set(self, key: str, value: str, category: str = "general") -> None:
        """Encrypt and persist ``value`` under ``key``."""
        if not self._fernet:
            raise RuntimeError("credentials_vault not initialized — call initialize() first")
        ciphertext = self._fernet.encrypt(value.encode()).decode()
        self._entries[key] = {"ciphertext": ciphertext, "category": category}
        self._persist()

    def delete(self, key: str) -> bool:
        if key not in self._entries:
            return False
        self._entries.pop(key, None)
        self._persist()
        return True

    def list_keys(self) -> List[Dict[str, Any]]:
        """Return metadata for every credential, WITHOUT plaintext values."""
        out: List[Dict[str, Any]] = []
        for key, entry in self._entries.items():
            out.append({
                "key": key,
                "category": entry.get("category", "general"),
                "masked_preview": self._mask(key),
            })
        return out

    def has(self, key: str) -> bool:
        return key in self._entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mask(self, key: str) -> str:
        """Return first 4 + last 4 chars of the plaintext (or ``<empty>`` / ``<not set>``)."""
        value = self.get(key)
        if value is None:
            return "<not set>"
        if not value:
            return "<empty>"
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}…{value[-4:]}"

    def _persist(self) -> None:
        # Always write the local file (the cache), and mirror to Turso
        # when configured. A Turso failure is logged, never fatal — the
        # local file still holds the write.
        self._persist_local()
        self._persist_turso()

    def _persist_local(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            blob = {"version": 1, "entries": self._entries}
            self._path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
            log.info("credentials_persisted", count=len(self._entries))
        except Exception as e:
            log.error("credentials_persist_failed", error=str(e))

    def _persist_turso(self) -> None:
        if self._turso is None:
            return
        try:
            self._turso.save_all(self._entries)
            log.info("credentials_persisted_turso", count=len(self._entries))
        except RuntimeError as e:
            log.warning("turso_vault_persist_failed", error=str(e))


# Process-wide singleton
credentials_vault = CredentialsVault()
