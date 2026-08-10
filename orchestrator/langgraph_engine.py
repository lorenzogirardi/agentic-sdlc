"""B-001-030 / B-001-031 — LangGraph execution core.

Replaces `orchestrator.dag_scheduler.run_dag` as the agent execution engine.
Graph *construction* (this module's `build_graph`) stays pure: it only reads
the planner's DAG and the policy config to decide node/edge/interrupt
structure. Node *execution* (agents calling out to tools, LLMs, etc.) is the
effectful shell, unchanged from before — nodes still call `Agent.execute()`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.base import Agent, AgentContext
from orchestrator.dag_scheduler import topological_sort
from orchestrator.logging import get_logger
from orchestrator.policy_engine import PolicyEngine
from schemas.execution import ExecutionContext

logger = get_logger(__name__)


def _merge_step_results(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    return {**left, **right}


class GraphState(TypedDict):
    execution: ExecutionContext
    step_results: Annotated[dict[str, dict[str, Any]], _merge_step_results]
    verdict: str | None


class PolicyBlockedError(RuntimeError):
    def __init__(self, node: str, severity: str) -> None:
        super().__init__(f"node '{node}' blocked by policy (severity={severity})")
        self.node = node
        self.severity = severity


def _severities(result: dict[str, Any]) -> list[str]:
    findings = result.get("findings", [])
    return [f["severity"] for f in findings if isinstance(f, dict) and f.get("severity")]


RunAgent = Callable[[str, Agent, AgentContext], Awaitable[dict[str, Any]]]


def _make_node(
    name: str,
    agent: Agent,
    policy: PolicyEngine,
    work_dir: str,
    dry_run: bool,
    run_agent: RunAgent | None,
) -> Callable[[GraphState], Awaitable[dict[str, Any]]]:
    async def node(state: GraphState) -> dict[str, Any]:
        ctx = AgentContext(execution=state["execution"], work_dir=work_dir, dry_run=dry_run)
        logger.info("graph_node_start", node=name)
        result = await (run_agent(name, agent, ctx) if run_agent else agent.execute(ctx))

        for severity in _severities(result):
            if policy.should_block_on_severity(severity):
                logger.error("graph_node_blocked", node=name, severity=severity)
                raise PolicyBlockedError(name, severity)

        logger.info("graph_node_done", node=name)
        return {"step_results": {name: result}}

    return node


def build_graph(
    dag: dict[str, list[str]],
    agents: dict[str, Agent],
    policy: PolicyEngine,
    checkpointer: BaseCheckpointSaver,
    work_dir: str,
    dry_run: bool = True,
    approval_action: str = "merge",
    run_agent: RunAgent | None = None,
) -> CompiledStateGraph[GraphState, Any, GraphState, GraphState]:
    """Validate `dag` and compile it into a runnable LangGraph.

    Raises `orchestrator.dag_scheduler.DAGError` (or the `CycleDetectedError`
    subclass) before any graph node is created if the DAG has a missing
    dependency or a cycle — this reuses the same pure validation the legacy
    scheduler relied on.

    `run_agent`, if given, replaces the default `agent.execute(ctx)` call per
    node — lets a caller (e.g. `Orchestrator`) inject its own tracing/metrics/
    StepResult-recording wrapper around agent execution without this module
    needing to know about any of that.
    """
    topological_sort(dag)  # validates: raises DAGError/CycleDetectedError before any node exists

    missing_agents = sorted(name for name in dag if name not in agents)
    if missing_agents:
        raise ValueError(f"No agent registered for DAG node(s): {missing_agents}")

    dependents: dict[str, list[str]] = {name: [] for name in dag}
    for name, deps in dag.items():
        for dep in deps:
            dependents[dep].append(name)

    graph: StateGraph[GraphState, Any, GraphState, GraphState] = StateGraph(GraphState)

    for name, agent in agents.items():
        if name not in dag:
            continue
        graph.add_node(  # type: ignore[call-overload]
            name, _make_node(name, agent, policy, work_dir, dry_run, run_agent)
        )

    for name, deps in dag.items():
        if not deps:
            graph.add_edge(START, name)
        for dep in deps:
            graph.add_edge(dep, name)
        if not dependents[name]:
            graph.add_edge(name, END)

    interrupt_before = []
    if "reviewer" in dag and policy.requires_human_approval(approval_action):
        interrupt_before.append("reviewer")

    return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before or None)
