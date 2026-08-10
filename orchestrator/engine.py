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
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agents.base import Agent, AgentContext
from agents.code_quality import CodeQualityAgent
from agents.coding import CodingAgent
from agents.cost_eval import CostEvalAgent
from agents.docker import DockerAgent
from agents.docker_build import DockerBuildAgent
from agents.lint import LintAgent
from agents.observability import ObservabilityAgent
from agents.planner import PlannerAgent
from agents.repo_inspector import RepoInspectorAgent
from agents.reviewer import ReviewerAgent
from agents.security import SecurityAgent
from agents.terraform import TerraformAgent
from agents.test_pyramid import TestPyramidAgent
from integrations.github_adapter import GitHubAdapter
from integrations.opencode_adapter import OpenCodeAdapter
from observability.metrics import MetricsRecorder
from observability.tracing import setup_tracing
from orchestrator.execution_context import ExecutionStore
from orchestrator.langgraph_engine import GraphState, build_graph
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
    "docker_build": DockerBuildAgent,
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

        has_coding = "coding" in dag

        if has_coding:
            coding_result = await self._run_coding_loop(agent_context, ctx, dag)
            agent_results["coding"] = coding_result
            # Remove coding from DAG (already executed in conversation loop)
            dag = {
                k: [d for d in v if d != "coding"] for k, v in dag.items() if k not in ("coding",)
            }

        agents_to_run: dict[str, Agent] = {}
        for agent_name in dag:
            agent_cls = AGENT_REGISTRY.get(agent_name)
            if agent_cls is None:
                logger.warning("agent_not_found", agent_name=agent_name)
                continue
            if agent_cls is ReviewerAgent:
                continue
            agents_to_run[agent_name] = self._instantiate_agent(agent_cls)

        sm.transition(ExecutionState.IMPLEMENTING)
        self.store.update_state(ctx.execution_id, ExecutionState.IMPLEMENTING, ctx=ctx)

        # reviewer runs explicitly below, outside the graph — drop it (and any
        # agent name that failed to resolve above) from the DAG passed to
        # build_graph, which requires every node to have a registered agent.
        runnable_dag = {
            name: [d for d in deps if d in agents_to_run]
            for name, deps in dag.items()
            if name in agents_to_run
        }
        dag_results = await self._run_dag(runnable_dag, agents_to_run, ctx)
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

    async def _run_dag(
        self,
        dag: dict[str, list[str]],
        agents: dict[str, Agent],
        ctx: ExecutionContext,
    ) -> dict[str, dict]:
        """Execute a DAG of agents via the LangGraph execution core."""
        if not dag:
            return {}

        async def run_agent(name: str, agent: Agent, agent_ctx: AgentContext) -> dict:
            return await self._run_agent(agent, agent_ctx, ctx)

        graph = build_graph(
            dag,
            agents,
            self.policy,
            InMemorySaver(),
            work_dir=ctx.task.repository_path,
            dry_run=ctx.mode == ExecutionMode.DRY_RUN,
            run_agent=run_agent,
        )
        config: RunnableConfig = {"configurable": {"thread_id": ctx.execution_id}}
        state: GraphState = {"execution": ctx, "step_results": {}, "verdict": None}
        final = await graph.ainvoke(state, config)
        return dict(final["step_results"])

    async def _run_coding_loop(
        self,
        agent_context: AgentContext,
        ctx: ExecutionContext,
        dag: dict[str, list[str]],
        max_turns: int = 3,
    ) -> dict:
        """Agentic conversation: coding → verify → fix → repeat."""
        from agents.coding import CodingAgent
        from agents.lint import LintAgent
        from agents.test_pyramid import TestPyramidAgent

        if self.opencode is None:
            return {"success": False, "error": "Coding agent requires LLM"}

        coding = CodingAgent(opencode_adapter=self.opencode)
        test_agent = TestPyramidAgent(self.runner)
        lint_agent = LintAgent(self.runner)

        for turn in range(1, max_turns + 1):
            logger.info("coding_turn", turn=turn, execution_id=ctx.execution_id)

            coding_result = await self._run_agent(coding, agent_context, ctx)
            if not coding_result.get("success"):
                return {"success": False, "error": "Coding agent failed at turn {turn}"}

            test_result = await self._run_agent(test_agent, agent_context, ctx)
            lint_result = await self._run_agent(lint_agent, agent_context, ctx)

            test_ok = test_result.get("success", False)
            lint_ok = lint_result.get("success", False)

            if test_ok and lint_ok:
                logger.info("coding_converged", turn=turn)
                return {
                    "success": True,
                    "turns": turn,
                    "summary": f"Converged after {turn} turn(s)",
                    "changes": coding_result.get("changes", []),
                }

            # Feed failures back to the coding agent for the next turn
            feedback = []
            if not test_ok:
                findings = test_result.get("findings", [])
                feedback.append(
                    "Tests failed. Fix: "
                    + "; ".join(f.get("summary_line", str(f)) for f in findings)
                )
            if not lint_ok:
                findings = lint_result.get("findings", [])
                feedback.append(
                    "Lint issues: " + "; ".join(f.get("output", "")[:200] for f in findings)
                )

            logger.warning("coding_feedback", turn=turn, feedback=feedback)
            coding.feedback = "\n".join(feedback)

        return {
            "success": False,
            "turns": max_turns,
            "error": f"Failed to converge after {max_turns} turns",
        }

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
        if agent_cls is DockerBuildAgent:
            return agent_cls(
                self.runner,
                image_repo=os.getenv("DOCKER_IMAGE_REPO", "ghcr.io/example/fractal"),
                push=bool(os.getenv("DOCKER_REGISTRY_PUSH", "")),
            )
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


async def _open_pr_if_changed(
    github: GitHubAdapter,
    owner: str,
    repo: str,
    branch_name: str,
    task: TaskSpec,
    execution_id: str,
    store: ExecutionStore,
    summary: str,
) -> str:
    """Commit the CodingAgent's file changes (if any) and open a PR.

    Returns the PR URL, or "" if there was nothing to commit or the adapter
    returned an empty/malformed URL (E25) — never silently pretends a PR
    exists when it doesn't.
    """
    executed_ctx = store.load(execution_id)
    coding_step = next(
        (s for s in (executed_ctx.steps if executed_ctx else []) if s.agent_name == "coding"),
        None,
    )
    changes = (coding_step.output or {}).get("changes", []) if coding_step else []
    files = {c["path"]: c["content"] for c in changes if c.get("path")}
    if not files:
        return ""

    await github.commit_changes(owner, repo, branch_name, f"agentic: {task.title}", files)
    pr_url = await github.create_pr(owner, repo, branch_name, task.base_branch, task.title, summary)
    if not pr_url:
        logger.error("github_pr_empty_url", branch=branch_name)
        return ""
    return pr_url


async def run_trello_polling(args: argparse.Namespace) -> int:
    """Poll Trello for cards labelled agent:run, execute pipeline, update cards."""

    from integrations.github_adapter import GitHubRESTAdapter
    from integrations.trello_adapter import TrelloRESTAdapter

    board_id = os.getenv("TRELLO_BOARD_ID", "")
    api_key = os.getenv("TRELLO_API_KEY", "")
    token = os.getenv("TRELLO_TOKEN", "")
    label_id = os.getenv("TRELLO_RUN_LABEL_ID", "")
    in_progress_list = os.getenv("TRELLO_IN_PROGRESS_LIST_ID", "6a784e64550433b46214797e")
    done_list = os.getenv("TRELLO_DONE_LIST_ID", "6a784e64550433b46214797f")
    todo_list = os.getenv("TRELLO_TODO_LIST_ID", "6a784e64550433b46214797d")

    if not all([board_id, api_key, token, label_id]):
        logger.error("trello_missing_config")
        return 1

    trello = TrelloRESTAdapter(api_key=api_key, token=token, dry_run=False)

    store = ExecutionStore()
    policy_engine = PolicyEngine.from_yaml(args.policy)
    runner = ToolRunner(allowed_commands=policy_engine.get_allowed_commands())

    opencode: OpenCodeAdapter | None = None
    if not args.no_opencode:
        base_url = os.getenv("OPENCODE_BASE_URL", "")
        api_key_oc = os.getenv("OPENCODE_API_KEY", "")
        if base_url and api_key_oc:
            opencode = OpenCodeAdapter(base_url=base_url, api_key=api_key_oc)

    github: GitHubRESTAdapter | None = None
    gh_owner = args.github_owner or os.getenv("GITHUB_OWNER", "")
    gh_repo = args.github_repo or os.getenv("GITHUB_REPOSITORY", "")
    gh_token = os.getenv("GITHUB_TOKEN", "")
    if args.mode == "pr" and gh_owner and gh_repo and gh_token:
        github = GitHubRESTAdapter(token=gh_token, dry_run=False)

    orchestrator = Orchestrator(
        store=store,
        policy_engine=policy_engine,
        runner=runner,
        opencode=opencode,
    )

    while True:
        try:
            cards = await trello.fetch_cards(board_id=board_id, label_id=label_id)

            if not cards:
                logger.debug("trello_poll_no_cards")

            for card in cards:
                card_id = card.get("id", "")
                card_name = card.get("name", "?")
                logger.info("trello_card_processing", card_id=card_id, name=card_name)

                await trello.move_card(card_id, in_progress_list)
                await trello.add_comment(card_id, "⚙️ Orchestrator started...")

                task = trello.card_to_task(
                    card,
                    repository_path=os.getenv("TARGET_REPO_PATH", "."),
                    mode=ExecutionMode(args.mode),
                )

                branch_name = ""
                pr_url = ""
                if github and args.mode == "pr":
                    branch_name = f"agentic/{task.execution_id[:12]}"
                    try:
                        await github.create_branch(
                            gh_owner,
                            gh_repo,
                            branch_name,
                            task.base_branch,
                        )
                    except Exception as exc:
                        logger.warning("github_branch_failed", error=str(exc))

                report = await orchestrator.run(task)

                verdict = report.get("verdict", "UNKNOWN")

                if github and args.mode == "pr" and branch_name and verdict != "BLOCKED":
                    try:
                        pr_url = await _open_pr_if_changed(
                            github,
                            gh_owner,
                            gh_repo,
                            branch_name,
                            task,
                            report["execution_id"],
                            store,
                            report.get("summary", ""),
                        )
                    except Exception as exc:
                        logger.warning("github_pr_failed", error=str(exc))

                prefix = {
                    "PASS": "PASS",
                    "PASS_WITH_WARNINGS": "PASS*",
                    "BLOCKED": "BLOCKED",
                    "REQUIRES_HUMAN_APPROVAL": "REVIEW",
                }

                await trello.update_card_fields(
                    card_id,
                    name=f"[{prefix.get(verdict, verdict)}] {card_name}",
                )

                dur = report.get("total_duration_ms", 0)
                comment_lines = [
                    "## Execution Report\n",
                    f"**Verdict:** {verdict} | **Duration:** {dur:.0f}ms",
                    f"**Execution ID:** `{report['execution_id']}`",
                    f"**Branch:** `{branch_name}`" if branch_name else "",
                    f"**PR:** {pr_url}" if pr_url else "",
                    "\n### Agent Results\n",
                ]
                for a in report.get("agent_results", []):
                    s = "PASS" if a.get("status") == "SUCCESS" else "FAIL"
                    d = a.get("duration_ms", 0)
                    comment_lines.append(f"- {s} **{a['agent_name']}** ({d:.0f}ms)")

                if report.get("findings"):
                    comment_lines.append("\n### Findings\n")
                    for f in report["findings"][:8]:
                        comment_lines.append(f"- {f}")

                ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
                comment_lines.append(f"\n_Generated by Agentic SDLC — {ts}_")
                await trello.add_comment(card_id, "\n".join(comment_lines))

                if github and args.mode == "pr" and branch_name and pr_url:
                    try:
                        await github.add_pr_comment(
                            gh_owner,
                            gh_repo,
                            int(pr_url.split("/")[-1]),
                            "\n".join(comment_lines),
                        )
                    except Exception as exc:
                        logger.warning("github_pr_comment_failed", error=str(exc))

                dest = done_list if verdict == "PASS" else todo_list
                await trello.move_card(card_id, dest)

            if args.poll_interval == 0:
                break
            await asyncio.sleep(args.poll_interval)

        except Exception as exc:
            logger.error("trello_poll_failed", error=str(exc))
            if args.poll_interval == 0:
                return 1
            await asyncio.sleep(args.poll_interval)

    await trello.close()
    if github:
        await github.close()
    return 0


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
    parser.add_argument("--task", default=None, help="Path to task YAML file")
    parser.add_argument(
        "--poll-trello",
        action="store_true",
        help="Poll Trello for cards with agent:run label",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Trello poll interval in seconds (0 = single pass)",
    )
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
    parser.add_argument("--github-owner", default=None, help="GitHub owner for PR mode")
    parser.add_argument("--github-repo", default=None, help="GitHub repo for PR mode")
    args = parser.parse_args()

    if args.poll_trello:
        return await run_trello_polling(args)

    if not args.task:
        logger.error("Either --task or --poll-trello is required")
        return 1

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
