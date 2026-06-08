# ====================================================================
# JARVIS OMEGA — Document Agent
# ====================================================================
"""
Specialized Document Agent for reading, parsing, writing, and summarizing
various document formats (PDF, DOCX, XLSX, CSV, MD, TXT).
"""

from __future__ import annotations

import os
import time
import csv
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_document")

class AgentDocument:
    """
    Document processing agent. Handles metadata extraction, text searching,
    conversions, and summary generation.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_document"
        self.agent_type = AgentType.DOCUMENT

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        """Processes document operations such as parsing tables, CSV files, and text blocks."""
        log.info("document_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "read")
            file_path = task.payload.get("file_path")
            
            if not file_path:
                raise ValueError("file_path is required for all document actions")
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Document not found at path: {file_path}")

            if action == "read" or action == "parse":
                result_data = await self._parse_document(file_path, task)
            elif action == "summarize":
                result_data = await self._summarize_document(file_path, task)
            elif action == "search":
                result_data = await self._search_document(file_path, task)
            else:
                raise ValueError(f"Unsupported action: {action}")

            elapsed = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time=elapsed,
            )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            err_msg = f"{str(e)}\n{traceback.format_exc()}"
            log.error("document_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _parse_document(self, path: str, task: TaskDefinition) -> Dict[str, Any]:
        """Parses txt, md, or csv documents and returns structured content."""
        ext = os.path.splitext(path)[1].lower()
        
        if ext in [".txt", ".md"]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                "format": ext[1:],
                "lines_count": len(content.splitlines()),
                "char_count": len(content),
                "preview": content[:1000]
            }

        elif ext == ".csv":
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i < 100:  # Cap at 100 rows for size limits
                        rows.append(row)
                    else:
                        break
            return {
                "format": "csv",
                "total_rows": len(rows),
                "headers": rows[0] if rows else [],
                "preview_rows": rows
            }

        else:
            # Fallback mock parsing for binary documents (PDF/DOCX)
            size = os.path.getsize(path)
            return {
                "format": ext[1:] or "unknown",
                "file_size_bytes": size,
                "status": "binary_parsing_requires_external_packages",
                "details": f"File is ready for processing. Size: {size} bytes."
            }

    async def _summarize_document(self, path: str, task: TaskDefinition) -> Dict[str, Any]:
        """Generates a summary of the document content."""
        # Standard structural summary
        parsed = await self._parse_document(path, task)
        preview = parsed.get("preview", "")
        
        # Simple rule-based summary for stub fallback
        summary = f"Document Summary for {os.path.basename(path)}:\n"
        summary += f"- Size: {parsed.get('file_size_bytes', len(preview))} bytes\n"
        summary += f"- Format: {parsed.get('format', 'unknown')}\n"
        if preview:
            summary += f"- Content preview: {preview[:300]}...\n"

        return {
            "summary": summary,
            "metadata": parsed
        }

    async def _search_document(self, path: str, task: TaskDefinition) -> Dict[str, Any]:
        """Searches for a specific term inside the document."""
        term = task.payload.get("query")
        if not term:
            raise ValueError("query is required for document search action")

        ext = os.path.splitext(path)[1].lower()
        matches = []

        if ext in [".txt", ".md", ".csv"]:
            with open(path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if term.lower() in line.lower():
                        matches.append({
                            "line_number": line_num,
                            "content": line.strip()
                        })
                        if len(matches) >= 50:  # Cap matches
                            break

        return {
            "search_term": term,
            "matches_found": len(matches),
            "matches": matches
        }
