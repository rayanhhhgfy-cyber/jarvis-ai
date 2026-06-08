from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from shared.logger import get_logger
from backend.services.llm_service import llm_service
from backend.services.web_search_service import web_search_service

log = get_logger("social_sentinel")


class SocialSentinel:
    """
    Monitors LinkedIn and X/Twitter for professional mentions,
    connection requests, and opportunities. Drafts responses for Sir's approval.
    """

    def __init__(self) -> None:
        self._last_check: Optional[datetime] = None
        self._pending_drafts: List[Dict[str, Any]] = []

    async def scan_all(self) -> Dict[str, Any]:
        log.info("social_sentinel_scan")
        results = {"linkedin": [], "x": [], "drafts": []}

        linkedin_mentions = await self._check_linkedin()
        if linkedin_mentions:
            results["linkedin"] = linkedin_mentions

        x_mentions = await self._check_x()
        if x_mentions:
            results["x"] = x_mentions

        for mention in results.get("linkedin", []) + results.get("x", []):
            draft = await self._draft_response(mention)
            if draft:
                self._pending_drafts.append(draft)
                results["drafts"].append(draft)

        self._last_check = datetime.utcnow()
        return results

    async def _check_linkedin(self) -> List[Dict[str, Any]]:
        try:
            summary = await web_search_service.search_and_summarize(
                "LinkedIn notifications mentions opportunities site:linkedin.com/in"
            )
            if summary and "No web search results" not in summary:
                return [{"source": "linkedin", "content": summary[:1000], "timestamp": datetime.utcnow().isoformat()}]
        except Exception as e:
            log.warning("linkedin_scan_error", error=str(e))
        return []

    async def _check_x(self) -> List[Dict[str, Any]]:
        try:
            summary = await web_search_service.search_and_summarize(
                "Twitter mentions AI engineer opportunities site:twitter.com OR site:x.com"
            )
            if summary and "No web search results" not in summary:
                return [{"source": "x", "content": summary[:1000], "timestamp": datetime.utcnow().isoformat()}]
        except Exception as e:
            log.warning("x_scan_error", error=str(e))
        return []

    async def _draft_response(self, mention: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            draft = await llm_service.get_response(
                user_message=(
                    f"Draft a professional response to this {mention['source']} mention:\n"
                    f"{mention['content']}\n\n"
                    f"Tone: Professional, brief, from a senior AI engineer."
                ),
                inject_memory=False,
                system_instructions="You are JARVIS drafting responses for Sir's approval.",
            )
            return {
                "mention": mention,
                "draft": draft,
                "timestamp": datetime.utcnow().isoformat(),
                "approved": False,
            }
        except Exception as e:
            log.error("draft_response_error", error=str(e))
            return None

    def get_pending_drafts(self) -> List[Dict[str, Any]]:
        return [d for d in self._pending_drafts if not d.get("approved")]

    def approve_draft(self, draft_index: int) -> bool:
        if 0 <= draft_index < len(self._pending_drafts):
            self._pending_drafts[draft_index]["approved"] = True
            return True
        return False


social_sentinel = SocialSentinel()
