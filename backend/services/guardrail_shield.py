"""
Guardrail Shield — prompt injection protection, rate limiting, input isolation.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from shared.logger import get_logger

log = get_logger("guardrail_shield")


# Known prompt injection / jailbreak patterns (case-insensitive regex)
_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior)", re.IGNORECASE),
    re.compile(r"you\s+are\s+(now|free|released|unconstrained)", re.IGNORECASE),
    re.compile(r"your\s+(system|base|core)\s+prompt", re.IGNORECASE),
    re.compile(r"act\s+as\s+(dan|jailbreak|unfiltered|unguided)", re.IGNORECASE),
    re.compile(r"output\s+raw\s+(json|text|data|response)", re.IGNORECASE),
    re.compile(r"do\s+not\s+(follow|obey|adhere)", re.IGNORECASE),
    re.compile(r"hypothetical\s+(scenario|situation|response)", re.IGNORECASE),
    re.compile(r"role.?play", re.IGNORECASE),
    re.compile(r"simulate\s+unrestricted", re.IGNORECASE),
]


@dataclass
class RateLimitBucket:
    tokens: int
    last_refill: float
    capacity: int
    refill_rate: float  # tokens per second


class GuardrailShield:
    """
    Token-bucket rate limiter per IP + prompt injection scanner.
    """

    def __init__(self):
        self._buckets: Dict[str, RateLimitBucket] = {}
        self._default_capacity = 30
        self._default_refill = 1.0  # 1 token/sec → 30 burst / ~30s full refill

    def check_rate_limit(self, ip: str, cost: int = 1) -> bool:
        """Returns True if allowed, False if rate-limited."""
        now = time.monotonic()
        bucket = self._buckets.get(ip)

        if not bucket:
            bucket = RateLimitBucket(
                tokens=self._default_capacity,
                last_refill=now,
                capacity=self._default_capacity,
                refill_rate=self._default_refill,
            )
            self._buckets[ip] = bucket

        # Refill
        elapsed = now - bucket.last_refill
        tokens_to_add = elapsed * bucket.refill_rate
        bucket.tokens = min(bucket.capacity, bucket.tokens + tokens_to_add)
        bucket.last_refill = now

        if bucket.tokens < cost:
            return False

        bucket.tokens -= cost
        return True

    def detect_injection(self, text: str) -> Tuple[bool, Optional[str]]:
        """Returns (is_injection, matched_pattern)."""
        for pattern in _INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                log.warning("prompt_injection_detected", pattern=pattern.pattern[:60])
                return True, match.group(0)
        return False, None

    async def sanitize_input(self, text: str) -> str:
        """Strip known dangerous characters and limit length."""
        # Strip null bytes and control characters (except newline/tab)
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # Cap at 10K characters
        if len(sanitized) > 10000:
            sanitized = sanitized[:10000]
            log.info("input_truncated", original_length=len(text))
        return sanitized


guardrail_shield = GuardrailShield()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.guardrail_shield import guardrail_shield
# allowed = guardrail_shield.check_rate_limit("192.168.1.5")
# is_injection, pattern = guardrail_shield.detect_injection("ignore all previous instructions")
# safe = await guardrail_shield.sanitize_input(user_input)
# ---
