# ====================================================================
# JARVIS OMEGA — Security Unit Tests
# ====================================================================
"""
Unit tests for cryptography, encryption, JWT, and signature helper utilities.
"""

import time
from shared.security import (
    init_security,
    hash_password,
    verify_password,
    create_access_token,
    create_device_token,
    verify_token,
    verify_access_token,
    verify_device_token,
    generate_device_secret,
    generate_pairing_code,
    encrypt_data,
    decrypt_data,
    sign_request,
    verify_request_signature,
    sha256_hash,
)


def test_password_hashing():
    """Verify that password hashing and matching work correctly."""
    pwd = "SuperSecretPassword123!"
    hashed = hash_password(pwd)
    
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_jwt_lifecycle():
    """Verify JWT access and device token encoding, claims, and validation."""
    init_security(
        secret_key="test-secret-key-that-is-long-enough-for-jwt",
        encryption_key=None,  # Generates auto key
    )
    
    payload = {"user": "Sir", "role": "admin"}
    token = create_access_token(payload)
    
    # Check decode/verify
    claims = verify_token(token)
    assert claims is not None
    assert claims["user"] == "Sir"
    assert claims["type"] == "access"
    
    # Check access-specific verify
    access_claims = verify_access_token(token)
    assert access_claims is not None
    assert verify_device_token(token) is None


def test_device_tokens():
    """Verify device-specific token generation and validation."""
    init_security(secret_key="test-device-secret-key")
    
    token = create_device_token("dev-id-123", "PrimaryWorkstation")
    
    claims = verify_device_token(token)
    assert claims is not None
    assert claims["device_id"] == "dev-id-123"
    assert claims["device_name"] == "PrimaryWorkstation"
    assert claims["type"] == "device"
    
    assert verify_access_token(token) is None


def test_symmetric_encryption():
    """Verify symmetric encryption and decryption loops."""
    init_security()
    
    secret_message = "Keep this secret, Sir."
    encrypted = encrypt_data(secret_message)
    assert encrypted != secret_message
    
    decrypted = decrypt_data(encrypted)
    assert decrypted == secret_message


def test_request_signatures():
    """Verify HMAC signature creation and verification."""
    secret = "device-shared-secret-12345"
    device_id = "test-device"
    token = "session-token-abc"
    timestamp = str(time.time())
    
    sig = sign_request(device_id, token, timestamp, secret)
    assert len(sig) == 64  # SHA-256 hex digest is 64 chars
    
    assert verify_request_signature(device_id, token, timestamp, sig, secret) is True
    assert verify_request_signature(device_id, token, timestamp, "wrong_sig", secret) is False
    assert verify_request_signature(device_id, "wrong_token", timestamp, sig, secret) is False
    
    # Test expiration (simulating 10 minutes ago)
    old_timestamp = str(time.time() - 600)
    old_sig = sign_request(device_id, token, old_timestamp, secret)
    assert verify_request_signature(device_id, token, old_timestamp, old_sig, secret) is False


def test_sha256_hashing():
    """Test SHA-256 string hashing helper."""
    assert sha256_hash("hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
