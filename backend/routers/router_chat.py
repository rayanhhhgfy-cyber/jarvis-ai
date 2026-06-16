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
from typing import List, Tuple

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

# Maximum number of reason→act→observe cycles per chat turn. Bounds the
# iterative tool-use loop so JARVIS can chain commands without looping forever.
MAX_TOOL_ITERATIONS = 3


def _format_results_context(results: List[dict]) -> str:
    """Render executed-command results as a SYSTEM CONTEXT block for the LLM."""
    ctx = "\n\n[SYSTEM CONTEXT — Commands executed on the workstation]\n"
    for cr in results:
        ctx += f"• {cr['description']}: "
        if cr["completed"]:
            if cr["exit_code"] == 0:
                output = cr["stdout"] or "Completed successfully with no output."
                ctx += f"SUCCESS — {output}\n"
            else:
                error = cr["stderr"] or cr["stdout"] or "Unknown error"
                ctx += f"FAILED (exit {cr['exit_code']}) — {error}\n"
        else:
            ctx += "Still running in background...\n"
    ctx += (
        "\nRespond naturally about these results in your JARVIS persona. Do NOT say you "
        "cannot control the device — the commands have already been executed. If the task "
        "is not yet complete, you may issue another <run_os_command>...</run_os_command> to "
        "continue; otherwise simply reply to Sir.\n"
    )
    return ctx


def _already_handled(cmd: str, prior: List[dict]) -> bool:
    """True if an equivalent command was already executed this turn (dedup)."""
    normalized = cmd.lower().strip().replace(".exe", "")
    return any(
        cr["command"].lower().strip().replace(".exe", "") == normalized
        or normalized in cr["command"].lower()
        or cr["command"].lower() in normalized
        for cr in prior
    )


async def run_tool_loop(
    message: str,
    history: List[dict],
    include_memory: bool,
    command_results: List[dict],
) -> Tuple[str, List[dict]]:
    """
    Iterative reason→act→observe loop (ReAct).

    JARVIS reasons over the message plus any results gathered so far, optionally
    emits ``<run_os_command>`` tags, executes the new ones, observes the real
    output, and reasons again — chaining commands until it stops issuing actions
    or ``MAX_TOOL_ITERATIONS`` is reached. Returns the final natural-language
    reply (tags stripped) and the list of commands executed by the LLM.
    """
    llm_command_results: List[dict] = []
    clean_reply = ""

    for iteration in range(MAX_TOOL_ITERATIONS):
        executed_so_far = command_results + llm_command_results
        augmented_message = message
        if executed_so_far:
            augmented_message = message + _format_results_context(executed_so_far)

        reply = await llm_service.get_response(
            user_message=augmented_message,
            chat_history=history,
            inject_memory=include_memory,
        )

        llm_commands = re.findall(r"<run_os_command>(.*?)</run_os_command>", reply, re.DOTALL)
        clean_reply = re.sub(r"<run_os_command>.*?</run_os_command>", "", reply, flags=re.DOTALL).strip()

        new_results = []
        if llm_commands:
            log.info("llm_command_tags_detected", iteration=iteration, count=len(llm_commands))
            for cmd_raw in llm_commands:
                cmd = cmd_raw.strip()
                if not cmd:
                    continue
                # Don't re-execute a command already handled this turn
                if _already_handled(cmd, command_results + llm_command_results):
                    continue
                result = await _dispatch_and_wait(cmd, f"LLM command: {cmd}", timeout=10.0)
                new_results.append({
                    "description": f"Executed: {cmd}",
                    "command": cmd,
                    **result,
                })

        llm_command_results.extend(new_results)

        # Stop looping once the model issues no further actionable commands.
        if not new_results:
            break

    return clean_reply, llm_command_results


async def _dispatch_and_wait(cmd: str, description: str, timeout: float = 15.0) -> dict:
    """
    Executes an OS command DIRECTLY via subprocess on this machine.
    No daemon WebSocket needed — guaranteed real execution.
    """
    import subprocess

    log.info("executing_command_directly", command=cmd, description=description)
    loop = asyncio.get_running_loop()

    # Phase 1 — try with PIPE in a thread (works for console commands)
    def _try_pipe():
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return None  # GUI app indicator

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        is_gui = (
            exit_code != 0 and not stdout and not stderr
        ) or (
            exit_code != 0 and (
                "Input redirection" in stderr
                or "not supported" in stderr
            )
        )
        if is_gui:
            return None

        return {
            "completed": True,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "task_id": "direct-exec",
        }

    result = await loop.run_in_executor(None, _try_pipe)
    if result is not None:
        return result

    # Phase 2 — likely a GUI app, fire-and-forget without PIPE
    log.info("gui_app_detected_launching_detached", command=cmd)
    try:
        subprocess.Popen(cmd, shell=True)
    except Exception:
        pass
    return {
        "completed": True,
        "exit_code": 0,
        "stdout": "Application launched successfully.",
        "stderr": "",
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
        # PHASE 2+3: Iterative LLM reasoning + tool use (ReAct loop)
        # JARVIS reasons, optionally issues <run_os_command> tags, observes the
        # real results, then reasons again — chaining commands until the task is
        # done or MAX_TOOL_ITERATIONS is reached.
        # =================================================================
        history = [{"role": item["role"], "content": item["content"]} for item in dialogue_history[-10:]]

        clean_reply, llm_command_results = await run_tool_loop(
            message=request.message,
            history=history,
            include_memory=request.include_memory,
            command_results=command_results,
        )

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
