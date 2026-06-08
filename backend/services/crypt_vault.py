"""
Quantum Vault — zero-knowledge storage using AES-256-GCM.
Key derived from device fingerprint (MAC + hostname).

# pip install: cryptography
# TERMUX-NOTE: DMI/motherboard serial unavailable on Android.
#             Uses uuid.getnode() (MAC) + platform.node() (hostname) as fallback.
"""

from __future__ import annotations

import base64
import hashlib
import platform
import uuid
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.logger import get_logger

log = get_logger("crypt_vault")


def _derive_key() -> bytes:
    """
    Derive a 256-bit key from device MAC address + hostname.
    Standard AES-256-GCM — no fake quantum claims.
    """
    raw = f"{uuid.getnode()}:{platform.node()}:jarvis-omega-vault"
    return hashlib.sha256(raw.encode()).digest()


class CryptVault:
    """
    Encrypted key-value storage. Each value is AES-256-GCM encrypted
    with a random nonce. The key is derived once at startup.
    """

    def __init__(self):
        self._key = _derive_key()
        self._store: Dict[str, str] = {}  # name -> base64(ciphertext + nonce)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string. Returns base64-encoded ciphertext."""
        nonce = uuid.uuid4().bytes[:12]
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ciphertext).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a base64-encoded token. Returns plaintext."""
        raw = base64.b64decode(token)
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode()

    def store(self, name: str, value: str) -> None:
        """Encrypt and store a secret."""
        self._store[name] = self.encrypt(value)
        log.info("vault_stored", name=name)

    def retrieve(self, name: str) -> Optional[str]:
        """Retrieve and decrypt a secret."""
        token = self._store.get(name)
        if not token:
            return None
        try:
            return self.decrypt(token)
        except Exception as e:
            log.error("vault_retrieval_failed", name=name, error=str(e))
            return None

    def delete(self, name: str) -> bool:
        """Delete a stored secret."""
        if name in self._store:
            del self._store[name]
            return True
        return False

    def list_keys(self) -> list:
        return list(self._store.keys())


crypt_vault = CryptVault()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.crypt_vault import crypt_vault
# crypt_vault.store("OPENROUTER_API_KEY", "sk-or-...")
# key = crypt_vault.retrieve("OPENROUTER_API_KEY")
# ---
