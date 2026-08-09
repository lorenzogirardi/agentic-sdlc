"""E2E integration test — Vertical Slice dry-run."""

from pathlib import Path

import yaml

from orchestrator.engine import Orchestrator, load_task
from orchestrator.execution_context import ExecutionStore
from orchestrator.policy_engine import PolicyEngine
from runners.tool_runner import ToolRunner
from schemas.execution import TaskSpec


class TestEndToEndDryRun:
    async def test_full_pipeline_no_opencode(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "test-repo"
        repo_dir.mkdir()
        (repo_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
        (repo_dir / "tests").mkdir()
        (repo_dir / "tests" / "test_example.py").write_text("def test_pass(): assert True\n")

        task_yaml = tmp_path / "task.yaml"
        task_yaml.write_text(
            yaml.dump(
                {
                    "execution_id": "e2e-dry-001",
                    "title": "E2E Dry Run Test",
                    "description": "Test the full vertical slice",
                    "repository_path": str(repo_dir),
                    "acceptance_criteria": ["tests pass", "no lint errors"],
                    "requested_agents": [
                        "repo_inspector",
                        "lint",
                        "test_pyramid",
                        "security",
                    ],
                    "mode": "dry_run",
                }
            )
        )

        store = ExecutionStore(data_dir=str(tmp_path / "executions"))
        policy = PolicyEngine.from_yaml("policies/default.yaml")
        runner = ToolRunner(allowed_commands=policy.get_allowed_commands())

        orchestrator = Orchestrator(
            store=store,
            policy_engine=policy,
            runner=runner,
            opencode=None,
        )

        task = load_task(str(task_yaml))
        report = await orchestrator.run(task)

        assert report["execution_id"] == "e2e-dry-001"
        assert report["task_title"] == "E2E Dry Run Test"
        assert report["verdict"] in (
            "PASS",
            "PASS_WITH_WARNINGS",
            "BLOCKED",
            "REQUIRES_HUMAN_APPROVAL",
        )
        assert "final_state" in report
        assert "total_agent_steps" in report

    async def test_agent_failure_graceful(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "empty-repo"
        repo_dir.mkdir()

        task = TaskSpec(
            execution_id="fail-test",
            title="Failure Test",
            repository_path=str(repo_dir),
            requested_agents=["test_pyramid"],
        )

        store = ExecutionStore(data_dir=str(tmp_path / "executions"))
        policy = PolicyEngine.from_yaml("policies/default.yaml")
        runner = ToolRunner(allowed_commands=["python", "pytest"])

        orchestrator = Orchestrator(
            store=store,
            policy_engine=policy,
            runner=runner,
            opencode=None,
        )

        report = await orchestrator.run(task)
        assert report["verdict"] in ("BLOCKED", "REQUIRES_HUMAN_APPROVAL")

    async def test_resume_from_state(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "resume-repo"
        repo_dir.mkdir()
        (repo_dir / "pyproject.toml").write_text("[project]\nname='resume'\n")
        (repo_dir / "tests").mkdir()
        (repo_dir / "tests" / "test_example.py").write_text("def test_ok(): assert 1 == 1\n")

        task = TaskSpec(
            execution_id="resume-001",
            title="Resume Test",
            repository_path=str(repo_dir),
            requested_agents=["repo_inspector"],
        )

        store = ExecutionStore(data_dir=str(tmp_path / "executions"))
        policy = PolicyEngine.from_yaml("policies/default.yaml")
        runner = ToolRunner(allowed_commands=policy.get_allowed_commands())

        orchestrator = Orchestrator(
            store=store,
            policy_engine=policy,
            runner=runner,
            opencode=None,
        )

        _ = await orchestrator.run(task)
        ctx_after = store.load("resume-001")
        assert ctx_after is not None
        assert len(ctx_after.steps) >= 1
