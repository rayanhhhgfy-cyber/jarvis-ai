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

from cryptography.fernet import Fernet

from backend.config import settings
from shared.logger import get_logger

log = get_logger("credentials_vault")


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

    def __init__(self, storage_path: Optional[str] = None) -> None:
        self._path = Path(storage_path or "./storage/credentials.json")
        self._entries: Dict[str, Dict[str, str]] = {}
        self._fernet: Optional[Fernet] = None

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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            blob = {"version": 1, "entries": self._entries}
            self._path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
            log.info("credentials_persisted", count=len(self._entries))
        except Exception as e:
            log.error("credentials_persist_failed", error=str(e))


# Process-wide singleton
credentials_vault = CredentialsVault()
