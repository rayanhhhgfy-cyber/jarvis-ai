# ====================================================================
# JARVIS OMEGA — Clerk Security Utilities
# ====================================================================
"""
Clerk JWT verification for backend (FastAPI REST + WebSockets).

Implements:
- JWKS fetching with caching and key rotation tolerance
- JWT signature verification (RS256 by default)
- issuer/audience validation
- clock skew tolerance

This module is used by backend to strictly authorize:
- /api/* REST routes
- /ws/* WebSocket handshake
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import httpx
from jose import jwt as jose_jwt
from jose import JWTError
from jose.utils import base64url_decode

from shared.logger import get_logger

log = get_logger("clerk_security")


@dataclass(frozen=True)
class ClerkVerificationConfig:
    jwks_url: str
    issuer: str
    audience: str
    algorithms: Tuple[str, ...] = ("RS256",)
    clock_skew_seconds: int = 60
    jwks_cache_ttl_seconds: int = 3600


class JWKSCache:
    """
    Simple in-memory JWKS cache with TTL.
    Thread-safe behavior is provided by async locks in the verifier.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._cached_at: float = 0.0
        self._jwks: Dict[str, Any] = {"keys": []}

    def get(self) -> Dict[str, Any]:
        return self._jwks

    def is_expired(self) -> bool:
        if not self._cached_at:
            return True
        return (time.time() - self._cached_at) >= self._ttl_seconds

    def set(self, jwks: Dict[str, Any]) -> None:
        self._jwks = jwks
        self._cached_at = time.time()


class ClerkJWTVerifier:
    def __init__(self, config: ClerkVerificationConfig) -> None:
        self._config = config
        self._cache = JWKSCache(ttl_seconds=config.jwks_cache_ttl_seconds)
        self._lock = None  # created lazily to avoid importing asyncio at module import time

    async def _get_lock(self):
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _fetch_jwks(self) -> Dict[str, Any]:
        if not self._config.jwks_url:
            raise RuntimeError("Clerk JWKS URL is not configured.")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._config.jwks_url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            jwks = resp.json()

        if not isinstance(jwks, dict) or "keys" not in jwks:
            raise RuntimeError("Invalid JWKS payload from Clerk.")

        return jwks

    async def _ensure_jwks(self) -> Dict[str, Any]:
        lock = await self._get_lock()
        async with lock:
            if self._cache.is_expired():
                jwks = await self._fetch_jwks()
                self._cache.set(jwks)
        return self._cache.get()

    def _extract_kid(self, token: str) -> Optional[str]:
        # JWT header is base64url encoded first segment
        try:
            header_segment = token.split(".")[0]
            header_bytes = base64url_decode(header_segment.encode("utf-8"))
            import json

            header = json.loads(header_bytes.decode("utf-8"))
            kid = header.get("kid")
            return kid if isinstance(kid, str) else None
        except Exception:
            return None

    async def verify(self, token: str) -> Dict[str, Any]:
        """
        Verify Clerk JWT and return claims dict.

        Raises:
          - ValueError for missing/invalid token
          - PermissionError for verification failures
        """
        if not token or not isinstance(token, str):
            raise ValueError("Missing token")

        token = token.strip()
        if not token:
            raise ValueError("Missing token")

        try:
            kid = self._extract_kid(token)
            jwks = await self._ensure_jwks()

            # Build JWKs set for jose
            # jose-jwt can verify against the fetched JWKS if we pass key directly.
            # We'll locate matching RSA public key using kid; if kid missing, we fall back to searching.
            keys: List[Dict[str, Any]] = jwks.get("keys", []) if isinstance(jwks, dict) else []
            if kid:
                keys = [k for k in keys if k.get("kid") == kid] or keys

            if not keys:
                # refresh cache once
                jwks = await self._fetch_jwks()
                keys = jwks.get("keys", [])

            last_error: Optional[Exception] = None
            for jwk in keys:
                # jose expects a public key in JWK form via `key` param in some versions.
                # We use jose_jwt.decode with jwk as key.
                try:
                    claims = jose_jwt.decode(
                        token,
                        jwk,
                        algorithms=list(self._config.algorithms),
                        audience=self._config.audience if self._config.audience else None,
                        issuer=self._config.issuer if self._config.issuer else None,
                        options={
                            "verify_aud": bool(self._config.audience),
                            "verify_iss": bool(self._config.issuer),
                        },
                    )
                    if not isinstance(claims, dict):
                        raise PermissionError("Invalid token claims type.")
                    return claims
                except JWTError as e:
                    last_error = e
                    continue
                except Exception as e:
                    last_error = e
                    continue

            raise PermissionError(f"JWT verification failed: {str(last_error) if last_error else 'unknown'}")

        except PermissionError:
            raise
        except JWTError as e:
            raise PermissionError(f"JWT decode error: {str(e)}")
        except Exception as e:
            log.error("clerk_jwt_verify_error", error=str(e))
            raise PermissionError("Clerk JWT verification failed.")

    @staticmethod
    def get_user_id_from_claims(claims: Dict[str, Any]) -> str:
        # Clerk commonly uses `sub` as the user id.
        # Some tokens may contain `userId` or `sub`.
        for key in ("sub", "userId", "user_id"):
            v = claims.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raise PermissionError("Could not derive user_id from Clerk JWT claims.")

    @staticmethod
    def get_token_device_id_from_claims(claims: Dict[str, Any]) -> Optional[str]:
        # We rely on our device registry mapping; device_id can be provided by client
        # in a claim we control or a custom claim.
        for key in ("device_id", "deviceId", "device"):
            v = claims.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None
