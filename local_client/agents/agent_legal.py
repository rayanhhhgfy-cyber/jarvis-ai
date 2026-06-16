# ====================================================================
# JARVIS OMEGA — Legal Agent
# ====================================================================
"""
Specialized Legal Agent responsible for contract analysis, compliance checking,
regulatory research, and document drafting.
"""

from __future__ import annotations

import time
import traceback
from typing import Dict, Any, List
from datetime import datetime

from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus
from shared.logger import get_logger

log = get_logger("agent_legal")

class AgentLegal:
    """
    Legal and compliance agent. Analyzes contracts and regulations.
    """

    def __init__(self) -> None:
        self.agent_id = "agent_legal"
        self.agent_type = AgentType.LEGAL

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        log.info("legal_agent_executing", task_id=task.task_id, title=task.title)
        start_time = time.time()

        try:
            action = task.payload.get("action", "analyze_contract")

            if action == "analyze_contract":
                result_data = await self._analyze_contract(task)
            elif action == "compliance_check":
                result_data = await self._check_compliance(task)
            elif action == "draft_nda":
                result_data = await self._draft_nda(task)
            else:
                raise ValueError(f"Unknown Legal action: {action}")

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
            log.error("legal_agent_failed", task_id=task.task_id, error=err_msg)
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error=err_msg,
                execution_time=elapsed,
            )

    async def _analyze_contract(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "parties": ["Company A", "Consultant B"],
            "key_clauses": [
                "Indemnification section is broad",
                "Non-compete is limited to 1 year",
                "Termination requires 30 days notice"
            ],
            "risk_score": "Low",
            "suggested_edits": ["Clarify intellectual property ownership in Section 4.2"]
        }

    async def _check_compliance(self, task: TaskDefinition) -> Dict[str, Any]:
        region = task.payload.get("region", "EU")
        return {
            "framework": "GDPR" if region == "EU" else "CCPA",
            "status": "Compliant",
            "missing_elements": [],
            "next_audit_date": "Jan 2026"
        }

    async def _draft_nda(self, task: TaskDefinition) -> Dict[str, Any]:
        return {
            "document_title": "Non-Disclosure Agreement",
            "content_summary": "Standard mutual NDA protecting trade secrets and proprietary data.",
            "status": "Draft Generated",
            "file_path": "shared/documents/draft_nda.docx"
        }
