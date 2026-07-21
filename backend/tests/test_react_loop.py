# ====================================================================
# JARVIS OMEGA — Iterative Tool-Use (ReAct) Loop Tests
# ====================================================================
"""
Verifies the chat router's reason→act→observe loop: JARVIS chains
<run_os_command> tags across iterations using real results, dedups repeated
commands, and is bounded by MAX_TOOL_ITERATIONS.
"""

import importlib
import sys

import pytest

# The backend.routers package aliases `router_chat` to the APIRouter object,
# so fetch the actual module object from sys.modules.
importlib.import_module("backend.routers.router_chat")
router_chat = sys.modules["backend.routers.router_chat"]


def _scripted_llm(replies):
    """Return an async get_response stub that yields the given replies in order."""
    state = {"i": 0}

    async def _get_response(user_message, chat_history, inject_memory):
        idx = min(state["i"], len(replies) - 1)
        state["i"] += 1
        return replies[idx]

    return _get_response


def _fake_dispatch():
    """Records every executed command and returns a successful result."""
    executed = []

    async def _dispatch(cmd, description, timeout=10.0):
        executed.append(cmd)
        return {
            "completed": True,
            "exit_code": 0,
            "stdout": f"ran {cmd}",
            "stderr": "",
            "task_id": "test-exec",
        }

    return executed, _dispatch


async def test_loop_chains_commands_then_stops(monkeypatch):
    replies = [
        "Working on it, Sir. <run_os_command>echo step-one</run_os_command>",
        "Continuing. <run_os_command>echo step-two</run_os_command>",
        "All done, Sir.",
    ]
    executed, dispatch = _fake_dispatch()
    monkeypatch.setattr(router_chat.llm_service, "get_response", _scripted_llm(replies))
    monkeypatch.setattr(router_chat, "_dispatch_and_wait", dispatch)

    clean_reply, results = await router_chat.run_tool_loop(
        message="do a two step job",
        history=[],
        include_memory=False,
        command_results=[],
    )

    assert executed == ["echo step-one", "echo step-two"]
    assert [r["command"] for r in results] == ["echo step-one", "echo step-two"]
    assert clean_reply == "All done, Sir."
    # Tags must be stripped from the surfaced reply.
    assert "<run_os_command>" not in clean_reply


async def test_loop_is_bounded_by_max_iterations(monkeypatch):
    # Every reply emits a new unique command, so only the iteration cap stops it.
    replies = [f"step <run_os_command>echo cmd-{i}</run_os_command>" for i in range(10)]
    executed, dispatch = _fake_dispatch()
    monkeypatch.setattr(router_chat.llm_service, "get_response", _scripted_llm(replies))
    monkeypatch.setattr(router_chat, "_dispatch_and_wait", dispatch)

    _, results = await router_chat.run_tool_loop(
        message="loop forever",
        history=[],
        include_memory=False,
        command_results=[],
    )

    assert len(executed) == router_chat.MAX_TOOL_ITERATIONS
    assert len(results) == router_chat.MAX_TOOL_ITERATIONS


async def test_loop_dedups_repeated_command(monkeypatch):
    # The model repeats the same command; it should run once, then the loop ends
    # because the second iteration produces no *new* command.
    replies = [
        "<run_os_command>echo same</run_os_command>",
        "<run_os_command>echo same</run_os_command>",
        "done",
    ]
    executed, dispatch = _fake_dispatch()
    monkeypatch.setattr(router_chat.llm_service, "get_response", _scripted_llm(replies))
    monkeypatch.setattr(router_chat, "_dispatch_and_wait", dispatch)

    _, results = await router_chat.run_tool_loop(
        message="repeat",
        history=[],
        include_memory=False,
        command_results=[],
    )

    assert executed == ["echo same"]
    assert len(results) == 1


async def test_loop_runs_once_when_no_commands(monkeypatch):
    replies = ["Just a friendly reply, Sir."]
    executed, dispatch = _fake_dispatch()
    monkeypatch.setattr(router_chat.llm_service, "get_response", _scripted_llm(replies))
    monkeypatch.setattr(router_chat, "_dispatch_and_wait", dispatch)

    clean_reply, results = await router_chat.run_tool_loop(
        message="hello jarvis",
        history=[],
        include_memory=False,
        command_results=[],
    )

    assert executed == []
    assert results == []
    assert clean_reply == "Just a friendly reply, Sir."
