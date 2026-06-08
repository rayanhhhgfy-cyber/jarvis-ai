"""
Knowledge Ingestor — unstructured-text-to-markdown pipeline via FastAPI BackgroundTasks.

# pip install: httpx
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.logger import get_logger

log = get_logger("knowledge_ingestor")

_INGEST_DIR = Path.home() / ".jarvis" / "knowledge"
_INGEST_DIR.mkdir(parents=True, exist_ok=True)


class KnowledgeIngestor:
    """
    Accepts unstructured text, chunks into segments,
    converts each to markdown via LLM, and stores in knowledge directory.
    """

    def __init__(self):
        self._processing = False

    async def ingest_text(self, title: str, content: str, source: str = "manual") -> str:
        """
        Convert unstructured text to markdown and save.
        Returns the file path.
        """
        self._processing = True
        try:
            # Chunk large text
            chunks = self._chunk_text(content, max_chars=3000)
            md_parts: List[str] = []

            for i, chunk in enumerate(chunks):
                md = await self._convert_to_markdown(chunk, title, i + 1, len(chunks))
                md_parts.append(md)

            full_md = "\n\n".join(md_parts)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:50]
            filepath = _INGEST_DIR / f"{timestamp}_{safe_name}.md"
            filepath.write_text(f"# {title}\n\n> Source: {source}\n\n{full_md}")
            log.info("knowledge_ingested", title=title, path=str(filepath))
            return str(filepath)
        finally:
            self._processing = False

    def _chunk_text(self, text: str, max_chars: int = 3000) -> List[str]:
        """Split text into chunks at paragraph boundaries."""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) > max_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current += ("\n\n" + para) if current else para
        if current:
            chunks.append(current.strip())
        return chunks or [text]

    async def _convert_to_markdown(self, text: str, title: str, part: int, total: int) -> str:
        """Use LLM to convert text chunk to clean markdown."""
        prompt = f"""Convert the following text to clean markdown. Preserve all information. Use headings, lists, and code blocks as appropriate.

Title: {title} (Part {part}/{total})

Text:
{text}

Output only the markdown content."""
        try:
            from backend.services.llm_service import llm_service
            response = await llm_service.query(prompt)
            return response.strip().strip("```").strip()
        except Exception as e:
            log.debug("md_conversion_failed", error=str(e))
            return text

    async def ingest_url(self, url: str) -> Optional[str]:
        """Fetch URL content and ingest as knowledge."""
        try:
            from backend.services.mcp_client import mcp_client
            text = await mcp_client.extract_text(url)
            if text:
                return await self.ingest_text(f"Web: {url}", text, source=url)
        except Exception as e:
            log.error("url_ingest_failed", url=url[:80], error=str(e))
        return None

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all ingested knowledge documents."""
        docs = []
        for f in sorted(_INGEST_DIR.glob("*.md"), reverse=True):
            docs.append({
                "path": str(f),
                "name": f.stem,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return docs


knowledge_ingestor = KnowledgeIngestor()


# =========================================================================
# USAGE EXAMPLE
# =========================================================================
# ---
# from backend.services.knowledge_ingestor import knowledge_ingestor
# path = await knowledge_ingestor.ingest_text("My Notes", "Raw unstructured content here...")
# print(path)
# docs = knowledge_ingestor.list_documents()
# ---
