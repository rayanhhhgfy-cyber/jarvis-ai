# ====================================================================
# JARVIS OMEGA — SaaS Boilerplate Generator Service
# ====================================================================
"""
Boilerplate Generator Service. Handles prompt parsing, code generation,
local dev server launching, GitHub repository creation, and Vercel deployments.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings
from backend.services.llm_service import llm_service
from shared.logger import get_logger

log = get_logger("boilerplate_service")

# Map of running dev servers: project_id -> subprocess.Popen
RUNNING_SERVERS: Dict[str, subprocess.Popen] = {}
# Log streams: project_id -> List[str]
SERVER_LOGS: Dict[str, List[str]] = {}


class BoilerplateService:
    """
    Orchestrates the entire boilerplate build-and-deploy pipeline.
    """

    def __init__(self) -> None:
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.vercel_token = os.environ.get("VERCEL_TOKEN")
        self.vercel_team_id = os.environ.get("VERCEL_TEAM_ID")

    async def generate_project(self, prompt: str) -> Dict[str, Any]:
        """
        Parses prompt, selects framework, generates files via LLM,
        and saves them in the workspace.
        """
        project_id = f"build_{uuid.uuid4().hex[:12]}"
        log.info("boilerplate_generation_started", project_id=project_id, prompt=prompt[:100])

        system_instructions = (
            "You are an expert full-stack AI engineer. The user wants to generate a complete boilerplate "
            "project based on their prompt. You must generate all files needed for a fully functional skeleton. "
            "Format your response ONLY as a single JSON object with the following schema:\n"
            "{\n"
            "  \"framework\": \"nextjs\" | \"vite\" | \"fastapi\" | \"express\",\n"
            "  \"styling\": \"tailwind\" | \"css\",\n"
            "  \"database\": \"supabase\" | \"sqlite\" | \"postgres\" | \"none\",\n"
            "  \"auth\": \"clerk\" | \"supabase\" | \"none\",\n"
            "  \"description\": \"short description\",\n"
            "  \"files\": {\n"
            "     \"relative/file/path.tsx\": \"file content string...\"\n"
            "  }\n"
            "}\n"
            "Ensure that files like package.json, tailwind.config.js, next.config.js (or vite.config.ts), "
            "tsconfig.json, and source pages/components are complete and syntactically correct. "
            "Return ONLY the raw JSON. No markdown backticks, no markdown formatting, no explanations."
        )

        user_msg = f"Generate a project skeleton for: '{prompt}'"
        
        response = await llm_service.get_response(
            user_message=user_msg,
            inject_memory=False,
            system_instructions=system_instructions
        )

        # Parse JSON
        clean_json = response.strip()
        if clean_json.startswith("```"):
            clean_json = re.sub(r"^```(?:json)?\n", "", clean_json)
            clean_json = re.sub(r"\n```$", "", clean_json)
        clean_json = clean_json.strip()

        try:
            project_data = json.loads(clean_json)
        except Exception as e:
            log.error("boilerplate_json_parse_failed", raw_response=response, error=str(e))
            # Fallback mock skeleton if generation parsing failed
            project_data = self._get_fallback_skeleton(prompt)

        # Write files to workspace
        build_dir = Path(settings.workspace_dir) / "builds" / project_id
        build_dir.mkdir(parents=True, exist_ok=True)

        files = project_data.get("files", {})
        for filepath, content in files.items():
            file_path = build_dir / filepath
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            log.info("wrote_boilerplate_file", filepath=filepath)

        # Write metadata file for later reference
        meta = {
            "project_id": project_id,
            "prompt": prompt,
            "framework": project_data.get("framework", "nextjs"),
            "styling": project_data.get("styling", "tailwind"),
            "database": project_data.get("database", "none"),
            "auth": project_data.get("auth", "none"),
            "description": project_data.get("description", ""),
            "created_at": datetime.utcnow().isoformat(),
            "status": "generated",
            "files": list(files.keys())
        }
        (build_dir / ".jarvis_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return meta

    async def get_project_files(self, project_id: str) -> Dict[str, Any]:
        """Reads file tree and contents of a project."""
        build_dir = Path(settings.workspace_dir) / "builds" / project_id
        if not build_dir.exists():
            raise FileNotFoundError("Project build not found")

        file_tree = []
        file_contents = {}

        for p in build_dir.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and "node_modules" not in p.parts:
                rel_path = str(p.relative_to(build_dir)).replace("\\", "/")
                file_tree.append(rel_path)
                try:
                    file_contents[rel_path] = p.read_text(encoding="utf-8")
                except Exception:
                    file_contents[rel_path] = "[Binary file]"

        # Read meta
        meta = {}
        meta_file = build_dir / ".jarvis_meta.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))

        return {
            "meta": meta,
            "file_tree": file_tree,
            "files": file_contents
        }

    async def save_project_file(self, project_id: str, filepath: str, content: str) -> bool:
        """Saves manual edits from Monaco editor."""
        build_dir = Path(settings.workspace_dir) / "builds" / project_id
        if not build_dir.exists():
            return False
        
        target_file = build_dir / filepath
        # Guard path traversal
        if not str(target_file.resolve()).startswith(str(build_dir.resolve())):
            return False
            
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")
        log.info("saved_project_file_edit", project_id=project_id, filepath=filepath)
        return True

    async def run_local_dev(self, project_id: str) -> Dict[str, Any]:
        """Launches project's dev server in the background."""
        build_dir = Path(settings.workspace_dir) / "builds" / project_id
        if not build_dir.exists():
            return {"success": False, "message": "Project build not found"}

        # Check if already running
        if project_id in RUNNING_SERVERS:
            proc = RUNNING_SERVERS[project_id]
            if proc.poll() is None:
                return {
                    "success": True,
                    "port": 3000,
                    "url": "http://localhost:3000",
                    "pid": proc.pid,
                    "message": "Server already running"
                }

        log.info("starting_local_dev_server", project_id=project_id)
        
        # Clean logs
        SERVER_LOGS[project_id] = []

        is_node = (build_dir / "package.json").exists()
        is_python = (build_dir / "requirements.txt").exists() or (build_dir / "main.py").exists()

        try:
            if is_node:
                # 1. Run npm install (non-blocking log capture)
                log.info("running_npm_install", project_id=project_id)
                SERVER_LOGS[project_id].append("[JARVIS] Running npm install...\n")
                
                install_proc = await asyncio.create_subprocess_exec(
                    "npm", "install",
                    cwd=str(build_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    shell=True
                )
                stdout, stderr = await install_proc.communicate()
                SERVER_LOGS[project_id].append(stdout.decode())
                if install_proc.returncode != 0:
                    SERVER_LOGS[project_id].append(stderr.decode())
                    log.error("npm_install_failed", project_id=project_id)

                # 2. Run npm run dev in background
                SERVER_LOGS[project_id].append("[JARVIS] Starting dev server...\n")
                
                # We use subprocess.Popen so it persists in python background
                proc = subprocess.Popen(
                    "npm run dev",
                    cwd=str(build_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True
                )
            elif is_python:
                # 1. Run pip install
                SERVER_LOGS[project_id].append("[JARVIS] Running pip install...\n")
                install_proc = await asyncio.create_subprocess_exec(
                    "pip", "install", "-r", "requirements.txt",
                    cwd=str(build_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    shell=True
                )
                stdout, stderr = await install_proc.communicate()
                SERVER_LOGS[project_id].append(stdout.decode())

                # 2. Run uvicorn/python
                SERVER_LOGS[project_id].append("[JARVIS] Starting python server...\n")
                proc = subprocess.Popen(
                    "uvicorn main:app --reload --port 8080",
                    cwd=str(build_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True
                )
            else:
                return {"success": False, "message": "Unknown project structure, no package.json or main.py found"}

            RUNNING_SERVERS[project_id] = proc

            # Start reading logs in background thread
            asyncio.create_task(self._stream_logs_task(project_id, proc))

            port = 3000 if is_node else 8080
            return {
                "success": True,
                "port": port,
                "url": f"http://localhost:{port}",
                "pid": proc.pid,
                "message": "Dev server started successfully"
            }
        except Exception as e:
            log.error("local_dev_server_failed", error=str(e))
            return {"success": False, "message": f"Failed to start local dev: {str(e)}"}

    async def _stream_logs_task(self, project_id: str, proc: subprocess.Popen) -> None:
        """Reads stdout from running subprocess and stores in log buffer."""
        loop = asyncio.get_running_loop()
        while proc.poll() is None:
            # Run blocking read in executor
            line = await loop.run_in_executor(None, proc.stdout.readline)
            if not line:
                await asyncio.sleep(0.1)
                continue
            SERVER_LOGS.setdefault(project_id, []).append(line)
            # Cap logs
            if len(SERVER_LOGS[project_id]) > 1000:
                SERVER_LOGS[project_id] = SERVER_LOGS[project_id][-1000:]
        
        # Read final logs
        remaining = proc.stdout.read()
        if remaining:
            SERVER_LOGS.setdefault(project_id, []).append(remaining)

    def get_server_logs(self, project_id: str) -> List[str]:
        """Retrieve server stdout log history."""
        return SERVER_LOGS.get(project_id, [])

    async def push_to_github(self, project_id: str, repo_name: str) -> str:
        """Creates GitHub repository and pushes project code."""
        build_dir = Path(settings.workspace_dir) / "builds" / project_id
        if not build_dir.exists():
            raise FileNotFoundError("Project build not found")

        if not self.github_token:
            log.warning("github_token_missing_mocking_push")
            return f"https://github.com/mock-user/{repo_name}"

        # Get github username
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json"
        }
        
        async with httpx.AsyncClient() as client:
            user_resp = await client.get("https://api.github.com/user", headers=headers)
            if user_resp.status_code != 200:
                raise Exception(f"Failed to fetch GitHub user: {user_resp.text}")
            username = user_resp.json()["login"]

            # Create Repository
            create_url = "https://api.github.com/user/repos"
            payload = {
                "name": repo_name,
                "description": "Boilerplate generated by JARVIS OMEGA",
                "private": False
            }
            create_resp = await client.post(create_url, headers=headers, json=payload)
            if create_resp.status_code not in (200, 201):
                # Check if repo already exists, if so reuse it
                if "already exists" not in create_resp.text:
                    raise Exception(f"GitHub repo creation failed: {create_resp.text}")

        # Git init and push
        def run_git(args: list[str]):
            subprocess.run(["git"] + args, cwd=str(build_dir), check=True, capture_output=True, text=True)

        try:
            # Prepare .gitignore
            gitignore = build_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("node_modules/\n.env\n.env.local\n.next/\nbuild/\ndist/\n", encoding="utf-8")

            run_git(["init"])
            # Check branch name, default to main
            try:
                run_git(["checkout", "-b", "main"])
            except Exception:
                pass
            run_git(["add", "."])
            run_git(["commit", "-m", "Initial commit from J.A.R.V.I.S. OMEGA"])
            
            # Remove remote if exists
            try:
                run_git(["remote", "remove", "origin"])
            except Exception:
                pass

            remote_url = f"https://{self.github_token}@github.com/{username}/{repo_name}.git"
            run_git(["remote", "add", "origin", remote_url])
            run_git(["push", "-u", "origin", "main", "--force"])

            log.info("github_push_completed", repo=f"github.com/{username}/{repo_name}")
            return f"https://github.com/{username}/{repo_name}"
        except Exception as e:
            log.error("git_push_failed", error=str(e))
            raise

    async def deploy_to_vercel(self, project_id: str, repo_url: str) -> str:
        """Deploys the repository to Vercel via Vercel Project API."""
        if not self.vercel_token:
            log.warning("vercel_token_missing_mocking_deploy")
            return "https://jarvis-mock-deployment.vercel.app"

        # Extract owner/repo
        match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
        if not match:
            raise Exception("Invalid GitHub repository URL")
        owner, repo = match.group(1), match.group(2)

        headers = {"Authorization": f"Bearer {self.vercel_token}"}
        
        # Add team parameter if available
        params = {}
        if self.vercel_team_id:
            params["teamId"] = self.vercel_team_id

        # 1. Create project linked to Github repo
        async with httpx.AsyncClient() as client:
            proj_url = "https://api.vercel.com/v9/projects"
            proj_payload = {
                "name": repo.lower(),
                "framework": "nextjs",
                "gitRepository": {
                    "type": "github",
                    "repo": f"{owner}/{repo}"
                }
            }
            proj_resp = await client.post(proj_url, headers=headers, params=params, json=proj_payload)
            if proj_resp.status_code not in (200, 201) and "already_exists" not in proj_resp.text:
                raise Exception(f"Failed to link project on Vercel: {proj_resp.text}")

            # 2. Trigger deployment
            deploy_url = "https://api.vercel.com/v13/deployments"
            deploy_payload = {
                "name": repo.lower(),
                "gitSource": {
                    "type": "github",
                    "ref": "main",
                    "repoId": proj_resp.json().get("link", {}).get("repoId") or 0
                }
            }
            deploy_resp = await client.post(deploy_url, headers=headers, params=params, json=deploy_payload)
            if deploy_resp.status_code not in (200, 201):
                raise Exception(f"Failed to trigger Vercel deployment: {deploy_resp.text}")

            deploy_data = deploy_resp.json()
            deploy_id = deploy_data["id"]
            
            # 3. Monitor
            log.info("vercel_deployment_triggered", deployment_id=deploy_id)
            result = await self._poll_vercel_deployment(deploy_id)
            if result["status"] == "READY":
                return result["url"]
            else:
                # Self-healing logic
                from backend.services.self_healing import self_healing
                build_dir = Path(settings.workspace_dir) / "builds" / project_id
                errors = await self_healing.extract_build_errors(deploy_id)
                heal_res = await self_healing.auto_fix_and_redeploy(str(build_dir), errors, repo)
                if heal_res["success"]:
                    return heal_res["url"]
                else:
                    raise Exception(f"Vercel deploy failed. Self-healing logs: {heal_res['message']}")

    async def _poll_vercel_deployment(self, deployment_id: str) -> Dict[str, Any]:
        """Polls Vercel deployment status."""
        headers = {"Authorization": f"Bearer {self.vercel_token}"}
        url = f"https://api.vercel.com/v13/deployments/{deployment_id}"
        
        # Poll for maximum 5 minutes
        for _ in range(30):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("status")
                        if status in ("READY", "ERROR", "CANCELED"):
                            return {
                                "status": status,
                                "url": f"https://{data.get('url')}" if data.get('url') else None,
                            }
            except Exception as e:
                log.error("vercel_poll_error", error=str(e))
            await asyncio.sleep(10)
            
        return {"status": "TIMEOUT", "url": None}

    def _get_fallback_skeleton(self, prompt: str) -> Dict[str, Any]:
        """Fallback mock project structure in case LLM parsing fails."""
        return {
            "framework": "nextjs",
            "styling": "tailwind",
            "database": "none",
            "auth": "none",
            "description": "Fallback boilerplate",
            "files": {
                "package.json": json.dumps({
                    "name": "jarvis-boilerplate",
                    "version": "0.1.0",
                    "private": True,
                    "scripts": {
                        "dev": "next dev",
                        "build": "next build",
                        "start": "next start"
                    },
                    "dependencies": {
                        "next": "^14.0.0",
                        "react": "^18.2.0",
                        "react-dom": "^18.2.0",
                        "lucide-react": "^0.300.0"
                    },
                    "devDependencies": {
                        "typescript": "^5.0.0",
                        "@types/react": "^18.2.0",
                        "tailwindcss": "^3.3.0",
                        "postcss": "^8.4.0",
                        "autoprefixer": "^10.4.0"
                    }
                }, indent=2),
                "src/app/layout.tsx": (
                    "import './globals.css'\n"
                    "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
                    "  return (\n"
                    "    <html lang='en'>\n"
                    "      <body className='bg-slate-950 text-white min-h-screen'>{children}</body>\n"
                    "    </html>\n"
                    "  )\n"
                    "}"
                ),
                "src/app/page.tsx": (
                    "import React from 'react'\n"
                    "export default function Page() {\n"
                    "  return (\n"
                    "    <div className='flex flex-col items-center justify-center min-h-screen text-center p-8'>\n"
                    "      <h1 className='text-4xl font-bold mb-4 bg-gradient-to-r from-blue-400 to-indigo-500 bg-clip-text text-transparent'>\n"
                    "        JARVIS Generated SaaS\n"
                    "      </h1>\n"
                    "      <p className='text-slate-400 max-w-md'>\n"
                    "        This application was fully generated via J.A.R.V.I.S. OMEGA.\n"
                    "      </p>\n"
                    "    </div>\n"
                    "  )\n"
                    "}"
                ),
                "src/app/globals.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n",
                "tailwind.config.js": "module.exports = { content: ['./src/**/*.{js,ts,jsx,tsx}'] };",
                "postcss.config.js": "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };"
            }
        }


boilerplate_service = BoilerplateService()
