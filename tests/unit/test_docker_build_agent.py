"""B-001-032 — DockerBuildAgent tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from agents.base import AgentContext
from agents.docker_build import DockerBuildAgent
from runners.tool_runner import ToolResult
from schemas.execution import ExecutionContext, TaskSpec


def _ctx(dry_run: bool, repository_path: str = "/repo") -> AgentContext:
    task = TaskSpec(execution_id="exec-42", title="t", repository_path=repository_path)
    execution = ExecutionContext(execution_id="exec-42", task=task)
    return AgentContext(execution=execution, work_dir=repository_path, dry_run=dry_run)


def _tool_result(exit_code: int, stderr: str = "") -> ToolResult:
    return ToolResult(
        command="docker",
        args=[],
        exit_code=exit_code,
        stdout="",
        stderr=stderr,
        duration_ms=1.0,
    )


class TestDryRun:
    async def test_dry_run_skips_build_entirely(self) -> None:
        runner = AsyncMock()
        agent = DockerBuildAgent(runner, image_repo="ghcr.io/acme/fractal")

        result = await agent.execute(_ctx(dry_run=True))

        runner.run.assert_not_called()
        assert result["success"] is True
        assert "dry" in result["summary"].lower()


class TestBuild:
    async def test_build_success_tags_with_execution_id(self) -> None:
        runner = AsyncMock()
        runner.run.return_value = _tool_result(0)
        agent = DockerBuildAgent(
            runner, image_repo="ghcr.io/acme/fractal", dockerfile_dir="examples/sample-service"
        )

        result = await agent.execute(_ctx(dry_run=False))

        runner.run.assert_awaited_once_with(
            "docker",
            ["build", "-t", "ghcr.io/acme/fractal:exec-42", "examples/sample-service"],
            cwd="/repo",
        )
        assert result["success"] is True
        assert result["image_tag"] == "ghcr.io/acme/fractal:exec-42"

    async def test_build_failure_is_unsuccessful(self) -> None:
        runner = AsyncMock()
        runner.run.return_value = _tool_result(1, stderr="no such file")
        agent = DockerBuildAgent(runner, image_repo="ghcr.io/acme/fractal")

        result = await agent.execute(_ctx(dry_run=False))

        assert result["success"] is False
        assert "no such file" in result["summary"]


class TestPush:
    async def test_push_skipped_by_default(self) -> None:
        runner = AsyncMock()
        runner.run.return_value = _tool_result(0)
        agent = DockerBuildAgent(runner, image_repo="ghcr.io/acme/fractal")

        await agent.execute(_ctx(dry_run=False))

        assert runner.run.await_count == 1

    async def test_push_runs_after_successful_build_when_enabled(self) -> None:
        runner = AsyncMock()
        runner.run.return_value = _tool_result(0)
        agent = DockerBuildAgent(runner, image_repo="ghcr.io/acme/fractal", push=True)

        result = await agent.execute(_ctx(dry_run=False))

        assert runner.run.await_count == 2
        calls = runner.run.await_args_list
        assert calls[1].args == ("docker", ["push", "ghcr.io/acme/fractal:exec-42"])
        assert result["pushed"] is True

    async def test_push_not_attempted_when_build_fails(self) -> None:
        runner = AsyncMock()
        runner.run.return_value = _tool_result(1, stderr="build error")
        agent = DockerBuildAgent(runner, image_repo="ghcr.io/acme/fractal", push=True)

        result = await agent.execute(_ctx(dry_run=False))

        assert runner.run.await_count == 1
        assert result["pushed"] is False
