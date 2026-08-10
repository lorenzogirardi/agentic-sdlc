"""B-001-030 / B-001-031 — LangGraph execution core tests."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agents.base import Agent, AgentContext
from orchestrator.dag_scheduler import CycleDetectedError
from orchestrator.langgraph_engine import PolicyBlockedError, build_graph
from orchestrator.policy_engine import PolicyEngine
from schemas.execution import ExecutionContext, TaskSpec
from schemas.policy import PolicyConfig


class RecordingAgent(Agent):
    def __init__(self, name: str, order: list[str], result: dict[str, Any] | None = None) -> None:
        self.name = name
        self._order = order
        self._result = result or {"agent_name": name, "success": True}
        self.execute_calls = 0

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        self.execute_calls += 1
        self._order.append(self.name)
        return self._result

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        return {"verified": True}


def _execution_context() -> ExecutionContext:
    task = TaskSpec(title="t", repository_path=".")
    return ExecutionContext(task=task)


def _policy(**overrides: Any) -> PolicyEngine:
    return PolicyEngine(PolicyConfig(**overrides))


class TestBuildGraphValidation:
    def test_cycle_raises_before_graph_built(self) -> None:
        order: list[str] = []
        dag = {"a": ["b"], "b": ["a"]}
        agents = {
            "a": RecordingAgent("a", order),
            "b": RecordingAgent("b", order),
        }
        with pytest.raises(CycleDetectedError):
            build_graph(dag, agents, _policy(), InMemorySaver(), work_dir=".")

    def test_missing_agent_raises_value_error(self) -> None:
        dag = {"a": [], "b": ["a"]}
        agents = {"a": RecordingAgent("a", [])}
        with pytest.raises(ValueError, match="b"):
            build_graph(dag, agents, _policy(), InMemorySaver(), work_dir=".")


class TestExecutionOrder:
    async def test_executes_in_topological_order(self) -> None:
        order: list[str] = []
        dag = {"a": [], "b": ["a"], "c": ["b"]}
        agents = {name: RecordingAgent(name, order) for name in dag}
        graph = build_graph(dag, agents, _policy(), InMemorySaver(), work_dir=".")

        config = {"configurable": {"thread_id": "exec-1"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        final = await graph.ainvoke(state, config)

        assert order == ["a", "b", "c"]
        assert set(final["step_results"]) == {"a", "b", "c"}

    async def test_diamond_dag_all_nodes_run(self) -> None:
        order: list[str] = []
        dag = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
        agents = {name: RecordingAgent(name, order) for name in dag}
        graph = build_graph(dag, agents, _policy(), InMemorySaver(), work_dir=".")

        config = {"configurable": {"thread_id": "exec-2"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        final = await graph.ainvoke(state, config)

        assert order[0] == "a"
        assert order[-1] == "d"
        assert set(final["step_results"]) == {"a", "b", "c", "d"}


class TestCheckpointResume:
    async def test_checkpoint_round_trip(self) -> None:
        order: list[str] = []
        dag = {"a": [], "b": ["a"]}
        agents = {name: RecordingAgent(name, order) for name in dag}
        checkpointer = InMemorySaver()
        graph = build_graph(dag, agents, _policy(), checkpointer, work_dir=".")

        config = {"configurable": {"thread_id": "exec-resume"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        await graph.ainvoke(state, config)

        snapshot = await graph.aget_state(config)
        assert snapshot.values["step_results"]["a"]["success"] is True
        assert snapshot.values["step_results"]["b"]["success"] is True


class TestSeverityBlocking:
    async def test_blocking_severity_raises_and_stops_downstream(self) -> None:
        order: list[str] = []
        dag = {"security": [], "reviewer": ["security"]}
        critical_result = {
            "agent_name": "security",
            "success": False,
            "findings": [{"severity": "critical", "summary": "sql injection"}],
        }
        agents: dict[str, Agent] = {
            "security": RecordingAgent("security", order, result=critical_result),
            "reviewer": RecordingAgent("reviewer", order),
        }
        policy = _policy(block_on_security_severity=["critical", "high"])
        graph = build_graph(dag, agents, policy, InMemorySaver(), work_dir=".")

        config = {"configurable": {"thread_id": "exec-blocked"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        with pytest.raises(PolicyBlockedError):
            await graph.ainvoke(state, config)

        assert agents["reviewer"].execute_calls == 0  # type: ignore[attr-defined]

    async def test_non_blocking_severity_continues(self) -> None:
        order: list[str] = []
        low_result = {
            "agent_name": "security",
            "success": True,
            "findings": [{"severity": "low", "summary": "minor"}],
        }
        dag = {"security": [], "reviewer": ["security"]}
        agents = {
            "security": RecordingAgent("security", order, result=low_result),
            "reviewer": RecordingAgent("reviewer", order),
        }
        policy = _policy(
            block_on_security_severity=["critical", "high"], require_human_approval_for=[]
        )
        graph = build_graph(dag, agents, policy, InMemorySaver(), work_dir=".")

        config = {"configurable": {"thread_id": "exec-not-blocked"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        final = await graph.ainvoke(state, config)

        assert order == ["security", "reviewer"]
        assert final["step_results"]["reviewer"]["success"] is True


class TestRunAgentHook:
    async def test_custom_run_agent_replaces_default_execute(self) -> None:
        order: list[str] = []
        wrapped_calls: list[str] = []
        dag = {"a": [], "b": ["a"]}
        agents = {name: RecordingAgent(name, order) for name in dag}

        async def run_agent(name: str, agent: Agent, ctx: AgentContext) -> dict[str, Any]:
            wrapped_calls.append(name)
            return await agent.execute(ctx)

        graph = build_graph(
            dag, agents, _policy(), InMemorySaver(), work_dir=".", run_agent=run_agent
        )

        config = {"configurable": {"thread_id": "exec-hook"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        await graph.ainvoke(state, config)

        assert wrapped_calls == ["a", "b"]
        assert order == ["a", "b"]


class TestHumanApprovalInterrupt:
    async def test_reviewer_interrupts_when_policy_requires_approval(self) -> None:
        order: list[str] = []
        dag = {"a": [], "reviewer": ["a"]}
        agents = {
            "a": RecordingAgent("a", order),
            "reviewer": RecordingAgent("reviewer", order),
        }
        policy = _policy(require_human_approval_for=["merge"])
        checkpointer = InMemorySaver()
        graph = build_graph(dag, agents, policy, checkpointer, work_dir=".")

        config = {"configurable": {"thread_id": "exec-approval"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        await graph.ainvoke(state, config)

        assert order == ["a"]  # halted before reviewer
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("reviewer",)

        await graph.ainvoke(None, config)
        assert order == ["a", "reviewer"]

    async def test_no_interrupt_when_policy_does_not_require_approval(self) -> None:
        order: list[str] = []
        dag = {"a": [], "reviewer": ["a"]}
        agents = {
            "a": RecordingAgent("a", order),
            "reviewer": RecordingAgent("reviewer", order),
        }
        policy = _policy(require_human_approval_for=[])
        graph = build_graph(dag, agents, policy, InMemorySaver(), work_dir=".")

        config = {"configurable": {"thread_id": "exec-no-approval"}}
        state = {"execution": _execution_context(), "step_results": {}, "verdict": None}
        await graph.ainvoke(state, config)

        assert order == ["a", "reviewer"]
