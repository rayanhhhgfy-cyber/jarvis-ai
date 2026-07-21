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


class _FlakyAgent:
    """Fails the first ``fail_times`` calls (shared across instances), then succeeds."""

    fail_times = 0
    calls = 0

    def __init__(self) -> None:
        self.agent_id = "flaky_agent"

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        type(self).calls += 1
        if type(self).calls <= type(self).fail_times:
            return TaskResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.FAILED,
                error="transient failure",
            )
        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=TaskStatus.COMPLETED,
            result={"echo": task.title, "attempt": type(self).calls},
        )


class _RepairAgent:
    """Returns a diagnosis so we can assert repair runs on permanent failure."""

    def __init__(self) -> None:
        self.agent_id = "agent_repair"

    async def execute_task(self, task: TaskDefinition) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=TaskStatus.COMPLETED,
            result={"root_cause_analysis": "diagnosed", "traceback_seen": task.payload.get("traceback")},
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
    """Phase 4: planner may return LLM-derived or template-derived steps."""
    orch = AgentOrchestrator()
    task = TaskDefinition(
        title="Build feature",
        description="",
        agent_type=AgentType.ORCHESTRATOR,
        payload={"goal": "Build a CLI tool"},
    )

    steps = await orch._plan_subtasks(task)

    # The planner must return at least one executable step. Whether the steps
    # came from the LLM or the deterministic template depends on whether
    # OPENROUTER_API_KEY is configured in the test environment.
    assert isinstance(steps, list)
    assert len(steps) >= 1
    for s in steps:
        assert "title" in s
        assert "agent_type" in s
        assert "payload" in s


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


async def test_subagent_retries_until_success(monkeypatch):
    """A flaky sub-agent should be retried up to max_retries before giving up."""
    orch = AgentOrchestrator()
    _FlakyAgent.fail_times = 2
    _FlakyAgent.calls = 0
    monkeypatch.setattr(orch, "_resolve_agent_class", lambda agent_type: _FlakyAgent)

    task = TaskDefinition(
        title="Flaky",
        description="",
        agent_type=AgentType.OS,
        payload={},
        max_retries=3,
    )

    outcome = await orch._run_subagent(AgentType.OS, task)
    assert outcome["status"] == TaskStatus.COMPLETED.value
    assert outcome["attempts"] == 3


async def test_subagent_failure_triggers_repair_diagnosis(monkeypatch):
    """When all attempts fail, the Repair agent produces a diagnosis."""
    orch = AgentOrchestrator()

    def _resolve(agent_type):
        if agent_type == AgentType.REPAIR:
            return _RepairAgent
        return _FakeAgent

    monkeypatch.setattr(orch, "_resolve_agent_class", _resolve)

    task = TaskDefinition(
        title="Will fail",
        description="",
        agent_type=AgentType.CODE,
        payload={"should_fail": True},
        max_retries=1,
    )

    outcome = await orch._run_subagent(AgentType.CODE, task)
    assert outcome["status"] == TaskStatus.FAILED.value
    assert outcome["attempts"] == 1
    assert "repair_analysis" in outcome
    assert outcome["repair_analysis"]["root_cause_analysis"] == "diagnosed"


async def test_subagent_auto_repair_can_be_disabled(monkeypatch):
    """payload.auto_repair=False skips the Repair diagnosis step."""
    orch = AgentOrchestrator()
    monkeypatch.setattr(orch, "_resolve_agent_class", lambda agent_type: _FakeAgent)

    task = TaskDefinition(
        title="Will fail",
        description="",
        agent_type=AgentType.CODE,
        payload={"should_fail": True, "auto_repair": False},
        max_retries=1,
    )

    outcome = await orch._run_subagent(AgentType.CODE, task)
    assert outcome["status"] == TaskStatus.FAILED.value
    assert "repair_analysis" not in outcome


def _async_value(value):
    async def _coro():
        return value

    return _coro()
