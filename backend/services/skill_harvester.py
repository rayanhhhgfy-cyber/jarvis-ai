"""
Skill Harvester — scrapes web for downloadable skill code.

# pip install: httpx, beautifulsoup4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from shared.logger import get_logger

log = get_logger("skill_harvester")


@dataclass
class ScrapedSkill:
    name: str
    source_url: str
    code: str
    description: str = ""


_SEARCH_SOURCES = [
    "https://github.com/topics/ai-agent-skill",
    "https://github.com/topics/assistant-plugin",
]


class SkillHarvester:
    """
    Scrapes public sources (GitHub, community repos) for skill code.
    Returns raw Python source strings suitable for skill_manager.install().
    """

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    async def harvest(self, max_skills: int = 5) -> List[ScrapedSkill]:
        """Harvest skills from configured sources."""
        results: List[ScrapedSkill] = []

        for url in _SEARCH_SOURCES:
            skills = await self._scrape_github_topic(url)
            results.extend(skills)
            if len(results) >= max_skills:
                break

        await self._http.aclose()
        log.info("skill_harvest_complete", count=len(results))
        return results[:max_skills]

    async def _scrape_github_topic(self, url: str) -> List[ScrapedSkill]:
        """Scrape a GitHub topic page for repo links."""
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            repos = []
            for h3 in soup.select("h3 a"):
                href = h3.get("href", "")
                if href and href.startswith("/"):
                    repos.append(f"https://github.com{href}")

            skills = []
            for repo_url in repos[:5]:
                skill = await self._scrape_repo_readme(repo_url)
                if skill:
                    skills.append(skill)
            return skills
        except Exception as e:
            log.debug("github_scrape_failed", url=url[:60], error=str(e))
            return []

    async def _scrape_repo_readme(self, repo_url: str) -> Optional[ScrapedSkill]:
        """Extract raw README content and attempt to find Python code blocks."""
        try:
            readme_url = f"{repo_url}/raw/main/README.md"
            resp = await self._http.get(readme_url)
            if resp.status_code != 200:
                readme_url = f"{repo_url}/raw/master/README.md"
                resp = await self._http.get(readme_url)
            if resp.status_code != 200:
                return None

            content = resp.text
            # Extract first Python code block
            soup = BeautifulSoup(content, "html.parser")
            code_blocks = soup.find_all("code")
            code = ""
            for block in code_blocks:
                if not code:
                    code = block.get_text()

            name = repo_url.rstrip("/").split("/")[-1]
            return ScrapedSkill(
                name=name,
                source_url=repo_url,
                code=code[:5000],
                description=content[:200].replace("\n", " ").strip(),
            )
        except Exception as e:
            log.debug("readme_scrape_failed", url=repo_url, error=str(e))
            return None


skill_harvester = SkillHarvester()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.skill_harvester import skill_harvester
# skills = await skill_harvester.harvest(max_skills=3)
# for s in skills:
#     print(s.name, s.source_url)
# ---
