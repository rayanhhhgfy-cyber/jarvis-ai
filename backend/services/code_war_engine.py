"""
CodeWar Engine — Builder vs RedTeam 3-pass evaluation via OpenRouter.

# pip install: httpx
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.logger import get_logger

log = get_logger("code_war_engine")


@dataclass
class CodeWarResult:
    pass_name: str
    score: int
    feedback: str
    errors: List[str] = field(default_factory=list)


class CodeWarEngine:
    """
    Three-pass automated code review:
    1. Builder — functional correctness, style, edge cases
    2. RedTeam — security, performance, injection vectors
    3. Referee — weighted final score and verdict
    """

    BUILDER_PROMPT = """You are a senior code reviewer (Builder). Evaluate the following code on:
- Functional correctness
- Code style and readability
- Edge case handling
- Input validation

Return a JSON object with:
- "score": integer 0-100
- "feedback": concise feedback string
- "errors": list of specific issues (empty if none)

Code:
{code}"""

    REDTEAM_PROMPT = """You are a red-team security auditor (RedTeam). Analyze the following code for:
- SQL injection, XSS, command injection
- Insecure deserialization
- Hardcoded secrets
- Race conditions or TOCTOU
- Rate limiting / DoS risk

Return a JSON object with:
- "score": integer 0-100 (100 = no findings)
- "feedback": concise security assessment
- "errors": list of specific vulnerabilities (empty if none)

Code:
{code}"""

    REFEREE_PROMPT = """You are the final referee. The Builder scored {builder_score} and found: {builder_errors}
The RedTeam scored {redteam_score} and found: {redteam_errors}

Return a JSON object with:
- "score": integer 0-100 (weighted: 0.6 * builder + 0.4 * redteam, minus penalty)
- "feedback": final verdict
- "errors": combined unique errors
- "verdict": "PASS" if score >= 70 else "FAIL"
"""

    def __init__(self):
        pass

    async def evaluate(self, code: str) -> CodeWarResult:
        """Run 3-pass evaluation and return final result."""
        builder = await self._query_llm(self.BUILDER_PROMPT.format(code=code[:3000]))
        redteam = await self._query_llm(self.REDTEAM_PROMPT.format(code=code[:3000]))
        referee = await self._query_llm(self.REFEREE_PROMPT.format(
            builder_score=builder.get("score", 0),
            builder_errors=builder.get("errors", []),
            redteam_score=redteam.get("score", 0),
            redteam_errors=redteam.get("errors", []),
        ))

        return CodeWarResult(
            pass_name="CodeWar",
            score=referee.get("score", 0),
            feedback=referee.get("feedback", ""),
            errors=referee.get("errors", []),
        )

    async def _query_llm(self, prompt: str) -> Dict[str, Any]:
        """Call OpenRouter LLM and parse JSON response."""
        try:
            from backend.services.llm_service import llm_service
            response = await llm_service.query(prompt)
            import json
            # Extract JSON from response
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            log.error("codewar_llm_failed", error=str(e))
            return {"score": 0, "feedback": f"LLM error: {e}", "errors": [str(e)]}


code_war_engine = CodeWarEngine()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.code_war_engine import code_war_engine
# result = await code_war_engine.evaluate("def foo():\n    return 1")
# print(result)
# ---
