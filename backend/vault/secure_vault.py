from __future__ import annotations

import json
import os
import base64
from pathlib import Path
from typing import Optional, Dict, Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from shared.logger import get_logger

log = get_logger("secure_vault")

VAULT_SALT = b"jarvis_omega_vault_salt_2026"


class SecureVault:
    """
    AES-256-GCM encrypted credential storage.
    Master key from env VARIS_VAULT_KEY or auto-generated from machine fingerprint.
    Data is encrypted at rest in a JSON file.
    """

    def __init__(self, vault_path: str = "./storage/vault.enc") -> None:
        self._vault_path = Path(vault_path)
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet: Optional[Fernet] = None
        self._cache: Dict[str, str] = {}
        self._master_key_bytes: Optional[bytes] = None

    def initialize(self, master_key: Optional[str] = None) -> None:
        key = master_key or os.environ.get("JARVIS_VAULT_KEY")
        if not key:
            import hashlib
            machine_id = self._get_machine_id()
            key = hashlib.sha256(machine_id.encode()).hexdigest()
        self._master_key_bytes = key.encode() if isinstance(key, str) else key
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=VAULT_SALT, iterations=600000)
        self._fernet = Fernet(base64.urlsafe_b64encode(kdf.derive(self._master_key_bytes)))
        self._load()
        log.info("secure_vault_initialized")

    def _get_machine_id(self) -> str:
        try:
            import subprocess
            r = subprocess.run(["wmic", "csproduct", "get", "uuid"], capture_output=True, text=True)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line and "-" in line and len(line) > 20:
                        return line
        except Exception:
            pass
        try:
            return os.environ.get("COMPUTERNAME", "jarvis-omega-default")
        except Exception:
            return "jarvis-omega-default"

    def _load(self) -> None:
        if not self._vault_path.exists():
            self._cache = {}
            return
        try:
            encrypted = self._vault_path.read_bytes()
            if encrypted:
                decrypted = self._fernet.decrypt(encrypted).decode()
                self._cache = json.loads(decrypted)
        except Exception as e:
            log.error("vault_load_failed", error=str(e))
            self._cache = {}

    def _save(self) -> None:
        if not self._fernet:
            return
        plaintext = json.dumps(self._cache, indent=2)
        encrypted = self._fernet.encrypt(plaintext.encode())
        self._vault_path.write_bytes(encrypted)

    def store(self, key: str, value: str) -> None:
        self._cache[key] = value
        self._save()
        log.info("vault_store", key=key)

    def retrieve(self, key: str) -> Optional[str]:
        return self._cache.get(key)

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def list_keys(self) -> list[str]:
        return list(self._cache.keys())

    def has_key(self, key: str) -> bool:
        return key in self._cache

    def migrate_from_env(self, env_path: str = ".env") -> int:
        if not os.path.exists(env_path):
            return 0
        count = 0
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if not v or v.endswith("_here") or "your_" in v.lower():
                    continue
                if not self.has_key(k):
                    self.store(k, v)
                    count += 1
        log.info("vault_migrated_from_env", count=count)
        return count

    def get_user_fernet(self, user_id: str) -> Fernet:
        """Derive a user-specific encryption key based on the master key and user_id."""
        if not self._fernet or not self._master_key_bytes:
            raise RuntimeError("Vault is not initialized")
        user_salt = VAULT_SALT + f"_{user_id}".encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=user_salt,
            iterations=100000
        )
        user_key = base64.urlsafe_b64encode(kdf.derive(self._master_key_bytes))
        return Fernet(user_key)

    def rotate_key(self, new_master_key: str) -> None:
        """Change the master key and re-encrypt the vault."""
        if not self._fernet:
            raise RuntimeError("Vault is not initialized")
        new_key_bytes = new_master_key.encode() if isinstance(new_master_key, str) else new_master_key
        
        # Derive new Fernet key
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=VAULT_SALT, iterations=600000)
        new_fernet = Fernet(base64.urlsafe_b64encode(kdf.derive(new_key_bytes)))
        
        # Re-encrypt data
        plaintext = json.dumps(self._cache, indent=2)
        new_encrypted = new_fernet.encrypt(plaintext.encode())
        
        # Save to disk
        self._vault_path.write_bytes(new_encrypted)
        
        # Update current state
        self._master_key_bytes = new_key_bytes
        self._fernet = new_fernet
        log.info("secure_vault_key_rotated")

    def export_encrypted(self) -> str:
        """Export the vault's encrypted database file as a base64 encoded string."""
        if not self._vault_path.exists():
            return ""
        return base64.b64encode(self._vault_path.read_bytes()).decode()

    def import_encrypted(self, encrypted_base64: str) -> bool:
        """Decrypt the imported base64 data to verify, then save and reload the vault."""
        if not self._fernet:
            raise RuntimeError("Vault is not initialized")
        try:
            encrypted_bytes = base64.b64decode(encrypted_base64.encode())
            # Attempt to decrypt with current key to check validity
            decrypted = self._fernet.decrypt(encrypted_bytes).decode()
            json.loads(decrypted) # Check JSON validity
            
            # Save and reload
            self._vault_path.write_bytes(encrypted_bytes)
            self._load()
            log.info("secure_vault_imported_successfully")
            return True
        except Exception as e:
            log.error("secure_vault_import_failed", error=str(e))
            return False


secure_vault = SecureVault()
