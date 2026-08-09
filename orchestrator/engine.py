from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agents.base import Agent, AgentContext
from agents.code_quality import CodeQualityAgent
from agents.coding import CodingAgent
from agents.cost_eval import CostEvalAgent
from agents.docker import DockerAgent
from agents.lint import LintAgent
from agents.observability import ObservabilityAgent
from agents.planner import PlannerAgent
from agents.repo_inspector import RepoInspectorAgent
from agents.reviewer import ReviewerAgent
from agents.security import SecurityAgent
from agents.terraform import TerraformAgent
from agents.test_pyramid import TestPyramidAgent
from integrations.opencode_adapter import OpenCodeAdapter
from observability.metrics import MetricsRecorder
from observability.tracing import setup_tracing
from orchestrator.dag_scheduler import run_dag
from orchestrator.execution_context import ExecutionStore
from orchestrator.logging import get_logger, setup_logging
from orchestrator.policy_engine import PolicyEngine
from orchestrator.state_machine import StateMachine
from runners.tool_runner import ToolRunner
from schemas.execution import (
    ExecutionContext,
    ExecutionMode,
    ExecutionState,
    StepResult,
    StepStatus,
    TaskSpec,
)

logger = get_logger(__name__)

AGENT_REGISTRY: dict[str, type[Agent] | None] = {
    "planner": PlannerAgent,
    "repo_inspector": RepoInspectorAgent,
    "lint": LintAgent,
    "test_pyramid": TestPyramidAgent,
    "security": SecurityAgent,
    "reviewer": ReviewerAgent,
    "coding": CodingAgent,
    "code_quality": CodeQualityAgent,
    "docker": DockerAgent,
    "terraform": TerraformAgent,
    "observability": ObservabilityAgent,
    "cost_eval": CostEvalAgent,
}


class Orchestrator:
    def __init__(
        self,
        store: ExecutionStore,
        policy_engine: PolicyEngine,
        runner: ToolRunner,
        opencode: OpenCodeAdapter | None = None,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self.store = store
        self.policy = policy_engine
        self.runner = runner
        self.opencode = opencode
        self.metrics = metrics or MetricsRecorder()
        self.tracer = setup_tracing()

    async def run(self, task: TaskSpec) -> dict:
        ctx = self.store.create_from_task(task)
        sm = StateMachine()

        logger.info(
            "execution_start",
            execution_id=ctx.execution_id,
            title=task.title,
            mode=task.mode,
        )

        try:
            agent_results = await self._execute_pipeline(ctx, sm)
            report = self._build_report(ctx, agent_results)
            self._save_report(ctx.execution_id, report)
            if ctx.started_at and ctx.finished_at:
                duration_s = (ctx.finished_at - ctx.started_at).total_seconds()
                self.metrics.record_task(report.get("verdict", "UNKNOWN"), duration_s)
            return report
        except Exception as exc:
            logger.error("execution_failed", error=str(exc), execution_id=ctx.execution_id)
            report = self._build_error_report(ctx, exc)
            self._save_report(ctx.execution_id, report)
            self.metrics.record_task("BLOCKED", 0.0)
            return report

    async def _execute_pipeline(self, ctx: ExecutionContext, sm: StateMachine) -> dict[str, dict]:
        ctx.started_at = datetime.now(UTC)
        agent_results: dict[str, dict] = {}

        sm.transition(ExecutionState.TRIAGE)
        self.store.update_state(ctx.execution_id, ExecutionState.TRIAGE, ctx=ctx)

        agent_context = AgentContext(
            execution=ctx,
            work_dir=ctx.task.repository_path,
            dry_run=ctx.mode == ExecutionMode.DRY_RUN,
        )

        planner = PlannerAgent(opencode_adapter=self.opencode)
        planner_result = await self._run_agent(planner, agent_context, ctx)
        agent_results["planner"] = planner_result
        sm.transition(ExecutionState.SPECIFIED)
        self.store.update_state(ctx.execution_id, ExecutionState.SPECIFIED, ctx=ctx)

        plan = planner_result.get("plan", {})
        dag = plan.get("dag", {})

        if not dag:
            logger.warning("empty_dag", execution_id=ctx.execution_id)
            dag = {
                "repo_inspector": [],
                "lint": ["repo_inspector"],
                "test_pyramid": ["repo_inspector"],
                "security": ["repo_inspector"],
            }

        sm.transition(ExecutionState.PLANNED)
        self.store.update_state(ctx.execution_id, ExecutionState.PLANNED, ctx=ctx)

        agents_to_run: dict[str, Agent] = {}
        for agent_name in dag:
            agent_cls = AGENT_REGISTRY.get(agent_name)
            if agent_cls is None:
                logger.warning("agent_not_found", agent_name=agent_name)
                continue
            agents_to_run[agent_name] = self._instantiate_agent(agent_cls)

        sm.transition(ExecutionState.IMPLEMENTING)
        self.store.update_state(ctx.execution_id, ExecutionState.IMPLEMENTING, ctx=ctx)

        async def run_agent_wrapper(name: str) -> dict:
            if name == "reviewer":
                return {"success": True, "agent_name": "reviewer", "skipped": True}
            agent = agents_to_run.get(name)
            if agent is None:
                return {"success": False, "error": f"Agent '{name}' not found"}
            return await self._run_agent(agent, agent_context, ctx)

        dag_results = await run_dag(
            dag,
            run_agent_wrapper,
            max_parallel=self.policy.config.max_parallel_agents,
        )
        agent_results.update(dag_results)

        sm.transition(ExecutionState.VERIFYING)
        self.store.update_state(ctx.execution_id, ExecutionState.VERIFYING, ctx=ctx)

        sm.transition(ExecutionState.REVIEW_REQUIRED)
        self.store.update_state(ctx.execution_id, ExecutionState.REVIEW_REQUIRED, ctx=ctx)

        reviewer = ReviewerAgent()
        reviewer_result = await self._run_agent(reviewer, agent_context, ctx)
        agent_results["reviewer"] = reviewer_result

        verdict = reviewer_result.get("verdict", "BLOCKED")
        if verdict == "BLOCKED":
            sm.transition(ExecutionState.BLOCKED)
            self.store.update_state(ctx.execution_id, ExecutionState.BLOCKED, ctx=ctx)
        elif verdict in ("PASS", "PASS_WITH_WARNINGS"):
            sm.transition(ExecutionState.DONE)
            self.store.update_state(ctx.execution_id, ExecutionState.DONE, ctx=ctx)

        ctx.finished_at = datetime.now(UTC)
        self.store.save(ctx)

        return agent_results

    async def _run_agent(
        self,
        agent: Agent,
        agent_context: AgentContext,
        ctx: ExecutionContext,
    ) -> dict:
        start = time.perf_counter()
        step = StepResult(
            agent_name=agent.name,
            status=StepStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

        try:
            with self.tracer.start_as_current_span("agent_execution") as span:
                span.set_attribute("agent.name", agent.name)
                span.set_attribute("execution.id", ctx.execution_id)
                result = await agent.execute(agent_context)
                span.set_attribute("agent.success", bool(result.get("success", False)))
            duration_ms = (time.perf_counter() - start) * 1000

            step.status = StepStatus.SUCCESS if result.get("success", False) else StepStatus.FAILED
            step.finished_at = datetime.now(UTC)
            step.duration_ms = duration_ms
            step.output = result
            step.error = result.get("error")

            self.store.add_step(ctx.execution_id, step, ctx=ctx)
            self.metrics.record_agent(
                agent.name,
                "success" if result.get("success", False) else "failure",
                duration_ms / 1000,
            )
            logger.info(
                "agent_done",
                agent=agent.name,
                success=result.get("success", False),
                duration_ms=duration_ms,
            )
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            step.status = StepStatus.FAILED
            step.finished_at = datetime.now(UTC)
            step.duration_ms = duration_ms
            step.error = str(exc)

            self.store.add_step(ctx.execution_id, step, ctx=ctx)
            logger.error("agent_error", agent=agent.name, error=str(exc))
            return {"success": False, "error": str(exc)}

    def _instantiate_agent(self, agent_cls: type[Agent]) -> Agent:
        if agent_cls is LintAgent:
            return agent_cls(self.runner)
        if agent_cls is TestPyramidAgent:
            return agent_cls(self.runner)
        if agent_cls is SecurityAgent:
            return agent_cls(self.runner)
        if agent_cls is CodeQualityAgent:
            return agent_cls(self.runner)
        if agent_cls is DockerAgent:
            return agent_cls(self.runner)
        if agent_cls is TerraformAgent:
            return agent_cls(self.runner)
        if agent_cls is PlannerAgent:
            return agent_cls(opencode_adapter=self.opencode)
        if agent_cls is CodingAgent:
            return agent_cls(opencode_adapter=self.opencode)
        return agent_cls()

    def _build_report(self, ctx: ExecutionContext, agent_results: dict[str, dict]) -> dict:
        total_duration = 0.0
        if ctx.started_at and ctx.finished_at:
            total_duration = (ctx.finished_at - ctx.started_at).total_seconds() * 1000

        reviewer = agent_results.get("reviewer", {})
        return {
            "execution_id": ctx.execution_id,
            "task_title": ctx.task.title,
            "final_state": ctx.state,
            "verdict": reviewer.get("verdict", "UNKNOWN"),
            "summary": reviewer.get("summary", ""),
            "total_duration_ms": total_duration,
            "total_agent_steps": len(ctx.steps),
            "agent_results": [
                {
                    "agent_name": s.agent_name,
                    "status": s.status,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in ctx.steps
            ],
            "findings": reviewer.get("findings", []),
            "warnings": reviewer.get("warnings", []),
            "errors": ctx.errors,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _build_error_report(self, ctx: ExecutionContext, exc: Exception) -> dict:
        return {
            "execution_id": ctx.execution_id,
            "task_title": ctx.task.title,
            "final_state": ExecutionState.BLOCKED,
            "verdict": "BLOCKED",
            "summary": f"Execution failed: {exc}",
            "total_duration_ms": 0,
            "total_agent_steps": len(ctx.steps),
            "agent_results": [],
            "findings": [],
            "warnings": [],
            "errors": [str(exc)],
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _save_report(self, execution_id: str, report: dict) -> None:
        report_path = Path("data/executions") / execution_id / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))


def load_task(path: str) -> TaskSpec:
    raw = yaml.safe_load(Path(path).read_text())
    mode = ExecutionMode(raw.get("mode", "dry_run"))
    return TaskSpec(
        execution_id=raw.get("execution_id", ""),
        title=raw["title"],
        description=raw.get("description", ""),
        repository_path=raw["repository_path"],
        base_branch=raw.get("base_branch", "main"),
        acceptance_criteria=raw.get("acceptance_criteria", []),
        requested_agents=raw.get("requested_agents", []),
        mode=mode,
        metadata=raw.get("metadata", {}),
    )


async def main() -> int:
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass

    setup_logging()

    parser = argparse.ArgumentParser(description="Agentic SDLC Platform")
    parser.add_argument("--task", required=True, help="Path to task YAML file")
    parser.add_argument(
        "--mode",
        default="dry_run",
        choices=["dry_run", "pr", "approval_required"],
        help="Execution mode",
    )
    parser.add_argument(
        "--policy",
        default="policies/default.yaml",
        help="Path to policy YAML file",
    )
    parser.add_argument(
        "--no-opencode",
        action="store_true",
        help="Disable OpenCode adapter (use fallback planner)",
    )
    args = parser.parse_args()

    if not Path(args.task).exists():
        logger.error("task_not_found", path=args.task)
        return 1

    task = load_task(args.task)

    store = ExecutionStore()
    policy_engine = PolicyEngine.from_yaml(args.policy)
    runner = ToolRunner(
        allowed_commands=policy_engine.get_allowed_commands(),
        secret_patterns=[],
    )

    opencode: OpenCodeAdapter | None = None
    if not args.no_opencode:
        base_url = os.getenv("OPENCODE_BASE_URL", "")
        api_key = os.getenv("OPENCODE_API_KEY", "")
        if base_url and api_key:
            opencode = OpenCodeAdapter(base_url=base_url, api_key=api_key)

    orchestrator = Orchestrator(
        store=store,
        policy_engine=policy_engine,
        runner=runner,
        opencode=opencode,
    )

    report = await orchestrator.run(task)

    print("\n" + "=" * 60)
    print(f"  Execution: {report['execution_id']}")
    print(f"  Task: {report['task_title']}")
    print(f"  Verdict: {report['verdict']}")
    print(f"  State: {report['final_state']}")
    print(f"  Summary: {report['summary']}")
    print("=" * 60)
    print(f"\nReport saved to: data/executions/{report['execution_id']}/report.json")

    if report.get("errors"):
        for e in report["errors"]:
            print(f"  ERROR: {e}")

    return 0 if report.get("verdict") != "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
