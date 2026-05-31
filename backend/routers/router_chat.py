# ====================================================================
# JARVIS OMEGA — Chat Router
# ====================================================================
"""
REST endpoints for processing natural language dialog from Sir. Integrates
with the command interpreter for device control, the MythoMax reasoning
engine for conversation, and pushes proactive task reports via WebSocket.
"""

from __future__ import annotations

import base64
import re
import asyncio
from typing import List

from fastapi import APIRouter, HTTPException, Depends, status

from shared.models import ChatRequest, ChatResponse, MemoryEntry, TaskDefinition
from shared.constants import MemoryCategory, AgentType, TaskStatus
from backend.services.llm_service import llm_service
from backend.services.tts_service import tts_service
from backend.services.memory_service import memory_service
from backend.services.command_interpreter import command_interpreter
from backend.task_manager import task_manager
from shared.logger import get_logger

log = get_logger("router_chat")
router = APIRouter(prefix="/api/chat", tags=["Chat"])

# Simple in-memory list for short term dialogue history tracking
dialogue_history: List[dict] = []


async def _dispatch_and_wait(cmd: str, description: str, timeout: float = 15.0) -> dict:
    """
    Executes an OS command DIRECTLY via subprocess on this machine.
    No daemon WebSocket needed — guaranteed real execution.
    """
    import subprocess

    log.info("executing_command_directly", command=cmd, description=description)

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            ),
            timeout=5.0,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "completed": True,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Command timed out after {}s".format(timeout),
                "task_id": "direct-exec",
            }

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        log.info("command_executed", exit_code=exit_code, stdout_len=len(stdout))

        return {
            "completed": True,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "task_id": "direct-exec",
        }

    except Exception as e:
        log.error("command_execution_failed", error=str(e))
        return {
            "completed": True,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "task_id": "direct-exec",
        }


@router.post("")
async def process_chat(request: ChatRequest):
    """Processes natural language messages from Sir and returns responses with TTS audio."""
    log.info("chat_request_received", message_len=len(request.message))

    try:
        # =================================================================
        # PHASE 1: Server-side command detection (bypasses LLM completely)
        # =================================================================
        detected_commands = command_interpreter.interpret(request.message)
        command_results = []

        if detected_commands:
            log.info("commands_detected_by_interpreter", count=len(detected_commands))
            for description, cmd in detected_commands:
                log.info("dispatching_command", description=description, command=cmd)
                result = await _dispatch_and_wait(cmd, description, timeout=10.0)
                command_results.append({
                    "description": description,
                    "command": cmd,
                    **result,
                })

        # =================================================================
        # PHASE 2: LLM reasoning (for conversation + fallback commands)
        # =================================================================
        history = [{"role": item["role"], "content": item["content"]} for item in dialogue_history[-10:]]

        # If commands were detected, tell the LLM about the results so it can
        # craft a natural response incorporating the execution output
        augmented_message = request.message
        if command_results:
            result_context = "\n\n[SYSTEM CONTEXT — Commands executed on the workstation]\n"
            for cr in command_results:
                result_context += f"• {cr['description']}: "
                if cr["completed"]:
                    if cr["exit_code"] == 0:
                        output = cr["stdout"] or "Completed successfully with no output."
                        result_context += f"SUCCESS — {output}\n"
                    else:
                        error = cr["stderr"] or cr["stdout"] or "Unknown error"
                        result_context += f"FAILED (exit {cr['exit_code']}) — {error}\n"
                else:
                    result_context += "Still running in background...\n"
            result_context += "\nRespond naturally about these results in your JARVIS persona. Do NOT say you cannot control the device — the commands have already been executed.\n"
            augmented_message = request.message + result_context

        reply = await llm_service.get_response(
            user_message=augmented_message,
            chat_history=history,
            inject_memory=request.include_memory,
        )

        # =================================================================
        # PHASE 3: Parse any <run_os_command> tags from LLM (fallback)
        # =================================================================
        llm_commands = re.findall(r"<run_os_command>(.*?)</run_os_command>", reply, re.DOTALL)
        clean_reply = re.sub(r"<run_os_command>.*?</run_os_command>", "", reply, flags=re.DOTALL).strip()

        # Execute any LLM-generated commands that weren't already handled
        llm_command_results = []
        if llm_commands:
            log.info("llm_command_tags_detected", count=len(llm_commands))
            for cmd_raw in llm_commands:
                cmd = cmd_raw.strip()
                if not cmd:
                    continue
                # Don't re-execute if interpreter already handled a similar command
                already_handled = any(
                    cr["command"].lower().strip() == cmd.lower().strip()
                    for cr in command_results
                )
                if not already_handled:
                    result = await _dispatch_and_wait(cmd, f"LLM command: {cmd}", timeout=10.0)
                    llm_command_results.append({
                        "description": f"Executed: {cmd}",
                        "command": cmd,
                        **result,
                    })

        # =================================================================
        # PHASE 4: Build the final response
        # =================================================================
        all_results = command_results + llm_command_results

        # If interpreter handled commands but LLM gave no useful reply, generate one
        if not clean_reply and all_results:
            clean_reply = "Certainly, Sir. Executing your request now."

        # Append execution results to the response
        result_text = ""
        for cr in all_results:
            if cr["completed"]:
                if cr["exit_code"] == 0:
                    output = cr["stdout"] or "Command completed successfully."
                    result_text += f"\n\n**⚡ {cr['description']}**\n```\n{output}\n```"
                else:
                    error = cr["stderr"] or cr["stdout"] or "Unknown error"
                    result_text += f"\n\n**⚠️ {cr['description']} (Exit {cr['exit_code']})**\n```\n{error}\n```"
            else:
                result_text += f"\n\n*🔄 {cr['description']} — running in background, Sir. I'll report when complete.*"

        final_reply = clean_reply + result_text

        # Store dialogue in history
        dialogue_history.append({"role": "user", "content": request.message})
        dialogue_history.append({"role": "assistant", "content": final_reply})

        # Store in memory database
        memory_id = ""
        if request.include_memory:
            try:
                memory_id = await memory_service.add_memory(
                    content=f"Sir said: '{request.message}'. JARVIS responded: '{final_reply}'",
                    category=MemoryCategory.CONVERSATIONS,
                    source="chat_session",
                    tags=["interaction", "chat_log"],
                )
            except Exception as mem_err:
                log.error("auto_memory_storage_failed", error=str(mem_err))

        # Generate TTS audio for the clean text (no markdown/code blocks)
        tts_text = clean_reply  # Speak only the natural language part
        audio_b64 = ""
        try:
            audio_bytes = await tts_service.generate_speech(tts_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            log.info("tts_generated_for_chat", audio_size=len(audio_bytes))
        except Exception as tts_err:
            log.error("tts_generation_failed_in_chat", error=str(tts_err))

        return {
            "content": final_reply,
            "conversation_id": request.conversation_id or "default_session",
            "agents_invoked": [AgentType.OS.value] if all_results else [],
            "tasks_created": [cr["task_id"] for cr in all_results if "task_id" in cr],
            "memories_stored": [memory_id] if memory_id else [],
            "audio_base64": audio_b64,
        }

    except Exception as e:
        log.error("chat_processing_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while generating reply: {str(e)}",
        )
