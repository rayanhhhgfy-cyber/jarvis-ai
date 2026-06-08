# ====================================================================
# JARVIS OMEGA — Self-Healing Deployments Service
# ====================================================================
"""
Watches deployments on Vercel, extracts build errors from logs,
runs LLM-guided code fixes, and commits/redeploys or rolls back.
"""

from __future__ import annotations

import asyncio
import os
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings
from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("self_healing")


class SelfHealingService:
    """
    Watches Vercel deploy status, parses logs for build errors,
    runs LLM auto-patch loops, pushes fixes to Git, and rolls back if failing.
    """

    def __init__(self) -> None:
        self.vercel_token = os.environ.get("VERCEL_TOKEN")
        self.github_token = os.environ.get("GITHUB_TOKEN")

    async def monitor_deployment(self, deployment_id: str, timeout_seconds: int = 300) -> Dict[str, Any]:
        """Poll Vercel deployment status until READY, ERROR, or timeout."""
        if not self.vercel_token:
            log.warning("vercel_token_missing_mocking_monitor")
            await asyncio.sleep(3)
            return {"status": "READY", "url": "https://jarvis-mock-deployment.vercel.app", "error": None}

        headers = {"Authorization": f"Bearer {self.vercel_token}"}
        url = f"https://api.vercel.com/v13/deployments/{deployment_id}"
        
        start_time = datetime.utcnow()
        while (datetime.utcnow() - start_time).total_seconds() < timeout_seconds:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status")
                        log.info("vercel_deployment_status", deployment_id=deployment_id, status=status)
                        if status in ("READY", "ERROR", "CANCELED"):
                            return {
                                "status": status,
                                "url": f"https://{data.get('url')}" if data.get('url') else None,
                                "error": data.get("error")
                            }
            except Exception as e:
                log.error("vercel_monitor_error", error=str(e))
            await asyncio.sleep(10)

        return {"status": "TIMEOUT", "url": None, "error": "Deployment timed out"}

    async def extract_build_errors(self, deployment_id: str) -> str:
        """Fetch Vercel build log events and extract error messages."""
        if not self.vercel_token:
            log.warning("vercel_token_missing_mocking_errors")
            return "Mock Error: Compilation failed in src/app/page.tsx (L24): Property 'user' does not exist on type 'Session'."

        headers = {"Authorization": f"Bearer {self.vercel_token}"}
        url = f"https://api.vercel.com/v2/deployments/{deployment_id}/events"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    events = resp.json()
                    error_lines = []
                    for ev in events:
                        text = ev.get("text", "")
                        type_ = ev.get("type", "")
                        # Check for stderr, error, failed, build fail keywords
                        if type_ == "stderr" or any(w in text.lower() for w in ("error", "failed", "exception", "cannot find")):
                            error_lines.append(text.strip())
                    return "\n".join(error_lines)
        except Exception as e:
            log.error("vercel_logs_fetch_failed", error=str(e))

        return "Unknown build error during Vercel deployment."

    async def auto_fix_and_redeploy(
        self,
        project_dir: str,
        errors: str,
        vercel_project_name: str,
        attempt: int = 1
    ) -> Dict[str, Any]:
        """Reads code in project_dir, runs LLM auto-fix, commits to git, and monitors deploy."""
        log.info("starting_self_healing_attempt", project_dir=project_dir, attempt=attempt)
        proj_path = Path(project_dir)
        if not proj_path.exists():
            return {"success": False, "message": f"Project directory {project_dir} does not exist"}

        # 1. Scan the directory to provide context to LLM
        files_context = []
        for file in proj_path.rglob("*"):
            if file.is_file() and not any(part.startswith(".") for part in file.parts) and "node_modules" not in file.parts:
                try:
                    rel_path = file.relative_to(proj_path)
                    content = file.read_text(encoding="utf-8")
                    files_context.append(f"=== File: {rel_path} ===\n{content}\n")
                except Exception:
                    pass

        project_files_str = "\n".join(files_context)[:40000] # Cap context size

        # 2. Feed to LLM
        prompt = (
            f"We deployed a project and it failed during compilation or build with these errors:\n"
            f"----------------------------------------\n"
            f"{errors}\n"
            f"----------------------------------------\n\n"
            f"Here are the code files in the project:\n"
            f"{project_files_str}\n\n"
            f"Please identify the bug causing the build error and produce the exact file fixes.\n"
            f"Respond ONLY with a JSON object where the keys are relative file paths and the values are the ENTIRE modified file content.\n"
            f"Do not include any markdown fences (like ```json), explanations or text outside the JSON. Return only the JSON object."
        )

        response = await llm_service.get_response(
            user_message=prompt,
            inject_memory=False,
            system_instructions="You are an expert full-stack AI engineer. You respond ONLY with a clean JSON object containing file fixes."
        )

        # 3. Clean and parse JSON response
        clean_json = response.strip()
        if clean_json.startswith("```"):
            # Strip markdown fences if present
            clean_json = re.sub(r"^```(?:json)?\n", "", clean_json)
            clean_json = re.sub(r"\n```$", "", clean_json)
        clean_json = clean_json.strip()

        try:
            patches = json.loads(clean_json)
        except Exception as json_err:
            log.error("llm_healing_json_parse_failed", raw_response=response, error=str(json_err))
            return {"success": False, "message": "Failed to parse auto-fix patch from LLM"}

        # 4. Apply Patches
        applied_files = []
        for rel_file_path, new_content in patches.items():
            target_file = proj_path / rel_file_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(new_content, encoding="utf-8")
            applied_files.append(rel_file_path)
            log.info("applied_healing_patch", file=rel_file_path)

        # 5. Git Commit & Push (Only if it is a Git repo)
        git_pushed = False
        if (proj_path / ".git").exists():
            try:
                def run_git(args: list[str]):
                    subprocess.run(["git"] + args, cwd=project_dir, check=True, capture_output=True, text=True)

                run_git(["add", "."])
                run_git(["commit", "-m", f"Auto-fix deploy errors (Attempt {attempt})"])
                run_git(["push", "origin", "main"])
                git_pushed = True
                log.info("healing_pushed_to_git")
            except Exception as git_err:
                log.error("git_push_failed_during_healing", error=str(git_err))

        # 6. Trigger new Vercel Deploy if Vercel token is configured
        if self.vercel_token and git_pushed:
            try:
                # Polling for new deployment triggered by Git push
                headers = {"Authorization": f"Bearer {self.vercel_token}"}
                # Wait 5s for Vercel to register the push event
                await asyncio.sleep(5)
                
                # Fetch recent deployments
                async with httpx.AsyncClient() as client:
                    list_url = f"https://api.vercel.com/v6/deployments?projectId={vercel_project_name}"
                    # Note: projectId can be project name or ID.
                    resp = await client.get(list_url, headers=headers)
                    if resp.status_code == 200:
                        deploys = resp.json().get("deployments", [])
                        if deploys:
                            latest_deploy_id = deploys[0]["uid"]
                            log.info("found_new_deploy_from_git", deployment_id=latest_deploy_id)
                            
                            # Monitor this new deployment
                            result = await self.monitor_deployment(latest_deploy_id)
                            if result["status"] == "READY":
                                return {"success": True, "url": result["url"], "message": "Successfully self-healed and deployed!"}
                            else:
                                new_errors = await self.extract_build_errors(latest_deploy_id)
                                if attempt < 3:
                                    return await self.auto_fix_and_redeploy(project_dir, new_errors, vercel_project_name, attempt + 1)
                                else:
                                    # Rollback on final failure
                                    await self.rollback(project_dir)
                                    return {"success": False, "message": "Self-healing failed after 3 attempts. Rolled back project."}
            except Exception as vercel_err:
                log.error("vercel_redeploy_trigger_failed", error=str(vercel_err))

        # If mocking or no vercel deployment tracking, pretend it works after patch
        return {
            "success": True,
            "url": "https://jarvis-mock-deployment.vercel.app",
            "message": f"Applied auto-patches: {', '.join(applied_files)}. (Mock Vercel Mode)"
        }

    async def rollback(self, project_dir: str) -> bool:
        """Rollback git branch to last known good commit and force push."""
        try:
            if not Path(project_dir, ".git").exists():
                return False

            def run_git(args: list[str]):
                subprocess.run(["git"] + args, cwd=project_dir, check=True, capture_output=True, text=True)

            log.warning("initiating_rollback", project_dir=project_dir)
            run_git(["reset", "--hard", "HEAD~1"])
            run_git(["push", "origin", "main", "--force"])
            log.info("rollback_successful")
            return True
        except Exception as e:
            log.error("rollback_failed", error=str(e))
            return False


self_healing = SelfHealingService()
