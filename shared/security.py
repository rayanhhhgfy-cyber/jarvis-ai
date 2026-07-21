# ====================================================================
# JARVIS OMEGA — Security Utilities
# ====================================================================
"""
JWT token management, password hashing, device authentication,
symmetric encryption (Fernet), and request signature verification.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
import jwt
from jwt import PyJWTError
import bcrypt

from shared.logger import get_logger

log = get_logger("security")

# ---- Password Hashing ----
# Switch to direct bcrypt to avoid passlib 3.13 compatibility bug


# ---- Default Config (overridden by backend config at runtime) ----
# IMPORTANT: ``_DEFAULT_SECRET`` MUST be set by ``init_security()`` before any
# JWT operation. Leaving it as the empty sentinel makes signature/verify
# operations fail loudly (raises ``RuntimeError``) instead of silently using a
# weak fallback that would invalidate existing tokens across restarts.
_DEFAULT_SECRET = ""
_DEFAULT_ALGORITHM = "HS256"
_ACCESS_EXPIRE_MINUTES = 60
_REFRESH_EXPIRE_DAYS = 30
_DEVICE_EXPIRE_DAYS = 365

# Module-level encryption key (set on startup)
_fernet: Optional[Fernet] = None


def init_security(
    secret_key: str = "",
    encryption_key: str = "",
    algorithm: str = _DEFAULT_ALGORITHM,
    access_expire_minutes: int = _ACCESS_EXPIRE_MINUTES,
    refresh_expire_days: int = _REFRESH_EXPIRE_DAYS,
    device_expire_days: int = _DEVICE_EXPIRE_DAYS,
) -> None:
    """
    Initialize security module with runtime configuration.

    Both ``secret_key`` and ``encryption_key`` are required — startup should
    have already validated this via ``settings.validate_security_settings()``.
    If they are missing here, we raise so the failure is obvious at the call
    site rather than producing silently-rotated keys.
    """
    global _DEFAULT_SECRET, _DEFAULT_ALGORITHM
    global _ACCESS_EXPIRE_MINUTES, _REFRESH_EXPIRE_DAYS, _DEVICE_EXPIRE_DAYS
    global _fernet

    placeholders = {
        "",
        "change_this_to_a_strong_random_secret_key",
        "jarvis-omega-change-this-secret",
        "jarvis-omega-default-secret-change-me",
    }
    if secret_key in placeholders:
        raise RuntimeError(
            "init_security called without a real BACKEND_SECRET_KEY — refusing "
            "to use a placeholder for JWT signing."
        )
    if not encryption_key:
        raise RuntimeError(
            "init_security called without ENCRYPTION_KEY — refusing to generate "
            "an ephemeral Fernet key (existing encrypted data would be lost)."
        )

    _DEFAULT_SECRET = secret_key
    _DEFAULT_ALGORITHM = algorithm
    _ACCESS_EXPIRE_MINUTES = access_expire_minutes
    _REFRESH_EXPIRE_DAYS = refresh_expire_days
    _DEVICE_EXPIRE_DAYS = device_expire_days

    _fernet = Fernet(
        encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    )


# ====================================================================
# JWT TOKENS
# ====================================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    if not _DEFAULT_SECRET:
        raise RuntimeError("Security module not initialized — call init_security() first")
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=_ACCESS_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, _DEFAULT_SECRET, algorithm=_DEFAULT_ALGORITHM)


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT refresh token."""
    if not _DEFAULT_SECRET:
        raise RuntimeError("Security module not initialized — call init_security() first")
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=_REFRESH_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, _DEFAULT_SECRET, algorithm=_DEFAULT_ALGORITHM)


def create_device_token(
    device_id: str,
    device_name: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a long-lived device token."""
    if not _DEFAULT_SECRET:
        raise RuntimeError("Security module not initialized — call init_security() first")
    data = {
        "device_id": device_id,
        "device_name": device_name,
        "type": "device",
    }
    expire = datetime.utcnow() + (expires_delta or timedelta(days=_DEVICE_EXPIRE_DAYS))
    data["exp"] = expire
    return jwt.encode(data, _DEFAULT_SECRET, algorithm=_DEFAULT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT token. Returns claims or None."""
    if not _DEFAULT_SECRET:
        log.error("verify_token_called_before_init_security")
        return None
    try:
        payload = jwt.decode(token, _DEFAULT_SECRET, algorithms=[_DEFAULT_ALGORITHM])
        return payload
    except PyJWTError:
        return None


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify an access token specifically."""
    claims = verify_token(token)
    if claims and claims.get("type") == "access":
        return claims
    return None


def verify_device_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a device token specifically."""
    claims = verify_token(token)
    if claims and claims.get("type") == "device":
        return claims
    return None


# ====================================================================
# PASSWORD HASHING
# ====================================================================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    pw_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False



# ====================================================================
# DEVICE SECRETS
# ====================================================================

def generate_device_secret() -> str:
    """Generate a cryptographically secure device secret."""
    return secrets.token_urlsafe(48)


def generate_pairing_code(length: int = 6) -> str:
    """Generate a numeric pairing code for device registration."""
    return "".join([str(secrets.randbelow(10)) for _ in range(length)])


def generate_session_token() -> str:
    """Generate a unique session token."""
    return secrets.token_urlsafe(32)


# ====================================================================
# ENCRYPTION (Fernet symmetric)
# ====================================================================

def encrypt_data(data: str) -> str:
    """Encrypt a string using Fernet symmetric encryption."""
    if _fernet is None:
        init_security()
    return _fernet.encrypt(data.encode()).decode()


def decrypt_data(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    if _fernet is None:
        init_security()
    return _fernet.decrypt(encrypted.encode()).decode()


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key().decode()


# ====================================================================
# REQUEST SIGNATURES
# ====================================================================

def sign_request(device_id: str, session_token: str, timestamp: str, secret: str) -> str:
    """Generate HMAC-SHA256 signature for WebSocket request validation."""
    message = f"{device_id}:{session_token}:{timestamp}"
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_request_signature(
    device_id: str,
    session_token: str,
    timestamp: str,
    signature: str,
    secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify request signature and check freshness."""
    try:
        ts = float(timestamp)
        if abs(time.time() - ts) > max_age_seconds:
            return False
    except (ValueError, TypeError):
        return False

    expected = sign_request(device_id, session_token, timestamp, secret)
    return hmac.compare_digest(expected, signature)


# ====================================================================
# HASHING
# ====================================================================

def sha256_hash(data: str | bytes) -> str:
    """Generate SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def sha256_file(filepath: str) -> str:
    """Generate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
