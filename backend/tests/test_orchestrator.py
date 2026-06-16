# ====================================================================
# JARVIS OMEGA — Orchestrator / Sub-agent Deployment Tests
# ====================================================================
"""
Tests for the supervisor orchestrator's ability to deploy sub-agents,
auto-plan high-level goals, and isolate per-sub-agent failures.
"""

import pytest

from local_client.agents.agent_orchestrator import AgentOrchestrator
from local_client.task_executor import LocalTaskExecutor
from local_client.agents import agent_orchestrator as orchestrator_module
from shared.models import TaskDefinition, TaskResult
from shared.constants import AgentType, TaskStatus


class _FakeAgent:
    """Stand-in sub-agent that succeeds or fails based on the task payload."""

    def __init__(self) -> None:
        self.agent_id = "fake_agent"

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        if task.payload.get("should_fail"):
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error="intentional failure",
            )
        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=TaskStatus.COMPLETED,
            result={"echo": task.title},
        )


def _all_fake(monkeypatch, orch: AgentOrchestrator) -> None:
    monkeypatch.setattr(orch, "_resolve_agent_class", lambda agent_type: _FakeAgent)


async def test_decompose_runs_supplied_subtasks_and_aggregates(monkeypatch):
    orch = AgentOrchestrator()
    _all_fake(monkeypatch, orch)

    task = TaskDefinition(
        title="Mission",
        description="multi-step mission",
        agent_type=AgentType.ORCHESTRATOR,
        payload={"subtasks": [
            {"title": "step-1", "agent_type": "os", "payload": {}},
            {"title": "step-2", "agent_type": "code", "payload": {"should_fail": True}},
            {"title": "step-3", "agent_type": "research", "payload": {}},
        ]},
    )

    result = await orch._decompose_and_run(task)

    assert result["subtasks_total"] == 3
    assert result["subtasks_succeeded"] == 2
    assert result["subtasks_failed"] == 1
    assert result["status"] == "completed_with_errors"
    assert len(result["orchestrated_results"]) == 3
    # Parent task tracks all spawned subtask ids
    assert len(task.subtasks) == 3


async def test_decompose_continue_on_error_false_stops_early(monkeypatch):
    orch = AgentOrchestrator()
    _all_fake(monkeypatch, orch)

    task = TaskDefinition(
        title="Mission",
        description="halt on first failure",
        agent_type=AgentType.ORCHESTRATOR,
        payload={
            "continue_on_error": False,
            "subtasks": [
                {"title": "step-1", "agent_type": "os", "payload": {"should_fail": True}},
                {"title": "step-2", "agent_type": "code", "payload": {}},
            ],
        },
    )

    result = await orch._decompose_and_run(task)

    assert result["subtasks_failed"] == 1
    assert result["subtasks_succeeded"] == 0
    assert len(result["orchestrated_results"]) == 1


async def test_auto_planning_uses_planner_when_no_subtasks():
    orch = AgentOrchestrator()
    task = TaskDefinition(
        title="Build feature",
        description="",
        agent_type=AgentType.ORCHESTRATOR,
        payload={"goal": "Build a CLI tool"},
    )

    steps = await orch._plan_subtasks(task)

    assert len(steps) == 3
    agent_types = {s["agent_type"] for s in steps}
    assert {"research", "code", "testing"} == agent_types


async def test_decompose_falls_back_to_planner(monkeypatch):
    orch = AgentOrchestrator()
    _all_fake(monkeypatch, orch)
    monkeypatch.setattr(
        orch,
        "_plan_subtasks",
        lambda task: _async_value([{"title": "planned", "agent_type": "os", "payload": {}}]),
    )

    task = TaskDefinition(
        title="Goal only",
        description="",
        agent_type=AgentType.ORCHESTRATOR,
        payload={"goal": "do something"},
    )

    result = await orch._decompose_and_run(task)
    assert result["subtasks_total"] == 1
    assert result["subtasks_succeeded"] == 1


async def test_delegate_unknown_agent_raises():
    orch = AgentOrchestrator()
    task = TaskDefinition(
        title="No such agent",
        description="",
        agent_type=AgentType.WORKER,
        payload={},
    )

    with pytest.raises(RuntimeError, match="No sub-agent is available"):
        await orch._delegate_to_agent(AgentType.WORKER, task)


async def test_task_executor_deploys_subagent_via_orchestrator(monkeypatch):
    """The executor must run specialized agents (no more 'not_implemented_yet')."""
    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "_resolve_agent_class",
        lambda agent_type: _FakeAgent,
    )

    executor = LocalTaskExecutor()
    task = TaskDefinition(
        title="Research task",
        description="investigate",
        agent_type=AgentType.RESEARCH,
        payload={},
    )

    result = await executor.execute(task)
    assert result.status == TaskStatus.COMPLETED
    assert result.result == {"echo": "Research task"}


def _async_value(value):
    async def _coro():
        return value

    return _coro()
