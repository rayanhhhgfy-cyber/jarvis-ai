# ====================================================================
# JARVIS OMEGA — pytest bootstrap
# ====================================================================
"""
Test bootstrap.

Phase 1 made BACKEND_SECRET_KEY and ENCRYPTION_KEY mandatory (fail-fast on
startup). Tests that exercise the FastAPI lifespan or the security module need
real values present BEFORE ``backend.config.Settings`` is constructed.

This conftest sets deterministic test-only values in the environment first.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import backend...` / `import shared...`
# work from any test directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Deterministic test-only bootstrap secrets. These are NEVER used in production
# — they exist solely so the test suite can boot the app and exercise security.
# Fernet keys must be 32 url-safe base64-encoded bytes (44 chars including '=').
_TEST_SECRET = "test-only-backend-secret-key-do-not-use-in-production-32chars"
_TEST_ENCRYPTION_KEY = "bzXnHRUj2agcycUn4lIIvhlOb_N148fYZ7YXZRFJyvY="  # valid Fernet key

os.environ.setdefault("BACKEND_SECRET_KEY", _TEST_SECRET)
os.environ.setdefault("ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY)


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def test_secret_key() -> str:
    """The deterministic BACKEND_SECRET_KEY used across the test session."""
    return _TEST_SECRET


@pytest.fixture(scope="session")
def test_encryption_key() -> str:
    """The deterministic ENCRYPTION_KEY used across the test session."""
    return _TEST_ENCRYPTION_KEY


@pytest.fixture(scope="session", autouse=True)
def _init_security_for_tests(test_secret_key, test_encryption_key):
    """
    Initialize the security module once for the whole test session so any code
    path that issues or verifies JWTs (device pairing, access tokens, etc.)
    works without each test having to call ``init_security()`` itself.
    """
    from shared.security import init_security
    init_security(
        secret_key=test_secret_key,
        encryption_key=test_encryption_key,
    )
    yield
