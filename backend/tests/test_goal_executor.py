# ====================================================================
# JARVIS OMEGA — Goal Executor Unit Tests
# ====================================================================
"""
Unit tests for the Mega Goal Executor (1000+ Step Engine).
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.goal_executor import GoalExecutor, GoalState

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def executor():
    return GoalExecutor()

@pytest.mark.anyio
@patch("backend.services.llm_service.llm_service")
async def test_goal_decomposition(mock_llm, executor):
    """Test that goals are decomposed into phases and steps via LLM."""
    mock_response = {
        "phases": [
            {
                "name": "Phase 1: Setup",
                "description": "Initialize setup",
                "steps": [
                    {"action": "Create folder structure", "command_hint": "mkdir test"},
                    {"action": "Create files", "command_hint": "echo content"}
                ]
            }
        ]
    }
    mock_llm.get_response = AsyncMock(return_value=json.dumps(mock_response))

    state = GoalState(goal_id="test_g1", goal="Set up mock project")
    await executor._decompose_goal(state)

    assert len(state.phases) == 1
    assert state.phases[0]["name"] == "Phase 1: Setup"
    assert len(state.phases[0]["steps"]) == 2
    assert state.phases[0]["steps"][0]["action"] == "Create folder structure"
    assert state.phases[0]["steps"][0]["command_hint"] == "mkdir test"

@pytest.mark.anyio
@patch("backend.services.llm_service.llm_service")
async def test_step_execution_success(mock_llm, executor):
    """Test that a step executes successfully and logs output."""
    mock_llm.get_response = AsyncMock(return_value=json.dumps({
        "command": "<run_os_command>echo Hello</run_os_command>",
        "explanation": "Print hello message"
    }))

    state = GoalState(goal_id="test_g2", goal="Echo Hello")
    state.phases = [{
        "name": "Phase 1",
        "steps": [{"action": "Echo Hello", "command_hint": "echo Hello", "status": "pending", "retries": 0}],
        "status": "pending"
    }]

    with patch.object(executor, "_dispatch_command", AsyncMock(return_value={"success": True, "output": "Hello"})):
        success = await executor._execute_single_step(state, state.phases[0]["steps"][0])
        assert success is True
        assert state.phases[0]["steps"][0]["output"] == "Hello"
        assert len(state.execution_log) == 1
        assert state.execution_log[0]["success"] is True
