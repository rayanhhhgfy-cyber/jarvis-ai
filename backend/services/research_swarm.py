# ====================================================================
# JARVIS OMEGA — Research Swarm Service
# ====================================================================
"""
Research Swarm Service.
Spawns parallel research queries across various web search sources,
crawls results, and synthesizes a comprehensive research report via LLM.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from backend.services.web_search_service import web_search_service
from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("research_swarm")


class ResearchSwarm:
    async def run_swarm(self, query: str, num_agents: int = 5) -> Dict[str, Any]:
        """
        Runs a parallel web research campaign.
        1. Generate diverse sub-queries and target sources based on the query.
        2. Execute DuckDuckGo searches in parallel.
        3. Fetch page contents from top URLs in parallel.
        4. Synthesize a comprehensive research report using the LLM.
        """
        log.info("starting_research_swarm", query=query, agents=num_agents)

        # Step 1: Generate sub-queries
        sub_queries = await self._generate_sub_queries(query, num_agents)
        log.info("swarm_sub_queries_generated", sub_queries=sub_queries)

        # Step 2: Search in parallel
        search_tasks = [
            web_search_service.search_web(q, max_results=3) for q in sub_queries
        ]
        search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Aggregate and deduplicate search results by URL
        unique_results: Dict[str, Dict[str, str]] = {}
        for res in search_results_list:
            if isinstance(res, dict) and res.get("success"):
                for r in res.get("results", []):
                    url = r.get("url")
                    if url and url not in unique_results:
                        unique_results[url] = {
                            "title": r.get("title", "No Title"),
                            "snippet": r.get("snippet", ""),
                            "url": url,
                        }

        if not unique_results:
            log.warning("swarm_no_search_results_found", query=query)
            return {
                "success": False,
                "report": "No web results could be retrieved for this query.",
                "sources": [],
            }

        # Step 3: Fetch top pages in parallel (up to 6 top URLs to save tokens)
        top_urls = list(unique_results.keys())[:6]
        fetch_tasks = [web_search_service.fetch_url(url, max_chars=4000) for url in top_urls]
        fetched_pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Aggregate crawled content
        research_context = []
        sources = []
        for i, page in enumerate(fetched_pages):
            if isinstance(page, dict) and page.get("success") and page.get("content"):
                url = page.get("url")
                meta = unique_results.get(url, {})
                title = meta.get("title", "Source Page")
                snippet = meta.get("snippet", "")
                content = page.get("content", "")

                research_context.append(
                    f"--- SOURCE #{i+1} ---\n"
                    f"Title: {title}\n"
                    f"URL: {url}\n"
                    f"Snippet: {snippet}\n\n"
                    f"Content:\n{content}\n"
                )
                sources.append({"title": title, "url": url})
            elif isinstance(page, dict):
                # Fall back to snippet if fetch failed
                url = page.get("url")
                meta = unique_results.get(url, {})
                if meta:
                    research_context.append(
                        f"--- SOURCE #{i+1} (Snippet Only) ---\n"
                        f"Title: {meta.get('title')}\n"
                        f"URL: {url}\n"
                        f"Snippet: {meta.get('snippet')}\n"
                    )
                    sources.append({"title": meta.get('title'), "url": url})

        # Step 4: Synthesize Report
        context_str = "\n".join(research_context)[:24000] # Cap context size
        report = await self._synthesize_report(query, context_str)

        log.info("swarm_research_report_synthesized", sources=len(sources))
        return {
            "success": True,
            "report": report,
            "sources": sources,
            "sub_queries": sub_queries,
        }

    async def _generate_sub_queries(self, main_query: str, count: int) -> List[str]:
        """Use LLM to generate diverse query variations and source restrictions."""
        system_prompt = (
            "You are an expert search engine strategist. Given a research topic, "
            f"generate exactly {count} distinct search queries to gather comprehensive information from different sources.\n"
            "Incorporate site restrictions (e.g. site:reddit.com, site:github.com, site:stackoverflow.com, site:wikipedia.org) "
            "where appropriate, or target different sub-topics, code examples, or documentation.\n"
            "Return ONLY a JSON list of strings. No explanations, no markdown formatting."
        )
        user_prompt = f"Topic: {main_query}"

        try:
            response = await llm_service.get_response(
                user_message=user_prompt,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            clean = response.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\n", "", clean)
                clean = re.sub(r"\n```$", "", clean)
            
            queries = json.loads(clean.strip())
            if isinstance(queries, list) and len(queries) > 0:
                return [str(q) for q in queries[:count]]
        except Exception as e:
            log.warning("sub_query_generation_failed_using_defaults", error=str(e))
        
        # Fallback sub-queries if LLM fails
        return [
            main_query,
            f"{main_query} documentation",
            f"{main_query} examples github",
            f"{main_query} site:reddit.com",
            f"{main_query} best practices",
        ][:count]

    async def _synthesize_report(self, query: str, context: str) -> str:
        """Synthesize collected web page content into a comprehensive markdown report."""
        system_prompt = (
            "You are JARVIS, an elite AI research assistant. Your task is to write a comprehensive, "
            "extremely detailed, and professional markdown research report based on the web crawl context provided.\n\n"
            "Structure your report using these headings:\n"
            "# Deep Research Report: [Topic]\n"
            "## Executive Summary\n"
            "## Technical Deep-Dive / Detailed Analysis\n"
            "## Practical Code Examples / Case Studies (if applicable)\n"
            "## Critical Considerations & Gotchas (what to watch out for)\n"
            "## References (include URLs and source names)\n\n"
            "Ensure the report is highly detailed, well-structured, objective, and contains real code/commands if the topic is technical. "
            "Use clear headings, bolding, lists, and formatting. Do not hallucinate links; use only the URLs present in the sources."
        )
        
        user_prompt = (
            f"Research Query: {query}\n\n"
            f"Collected Web Context:\n{context}"
        )

        try:
            report = await llm_service.get_response(
                user_message=user_prompt,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            return report
        except Exception as e:
            log.error("report_synthesis_failed", error=str(e))
            return f"# Research Report: {query}\n\nError generating report: {str(e)}"


# Singleton
research_swarm = ResearchSwarm()
