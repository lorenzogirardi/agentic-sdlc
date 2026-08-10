"""B-001-034 — regression test: create_pr must actually be called (was dead code)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from orchestrator.engine import _open_pr_if_changed
from orchestrator.execution_context import ExecutionStore
from schemas.execution import StepResult, StepStatus, TaskSpec


def _store_with_coding_step(
    tmp_path: Path, changes: list[dict[str, str]]
) -> tuple[ExecutionStore, TaskSpec]:
    store = ExecutionStore(data_dir=str(tmp_path / "executions"))
    task = TaskSpec(execution_id="exec-pr-1", title="Add health endpoint", repository_path=".")
    ctx = store.create_from_task(task)
    step = StepResult(
        agent_name="coding",
        status=StepStatus.SUCCESS,
        output={"changes": changes},
    )
    store.add_step(ctx.execution_id, step, ctx=ctx)
    return store, task


class TestOpenPrIfChanged:
    async def test_commits_and_opens_pr_when_changes_exist(self, tmp_path: Path) -> None:
        store, task = _store_with_coding_step(tmp_path, [{"path": "app.py", "content": "print(1)"}])
        github = AsyncMock()
        github.create_pr.return_value = "https://github.com/acme/repo/pull/7"

        pr_url = await _open_pr_if_changed(
            github, "acme", "repo", "agentic/exec-pr-1", task, "exec-pr-1", store, "summary"
        )

        github.commit_changes.assert_awaited_once_with(
            "acme",
            "repo",
            "agentic/exec-pr-1",
            "agentic: Add health endpoint",
            {"app.py": "print(1)"},
        )
        github.create_pr.assert_awaited_once_with(
            "acme", "repo", "agentic/exec-pr-1", task.base_branch, task.title, "summary"
        )
        assert pr_url == "https://github.com/acme/repo/pull/7"

    async def test_no_changes_skips_commit_and_pr(self, tmp_path: Path) -> None:
        store, task = _store_with_coding_step(tmp_path, [])
        github = AsyncMock()

        pr_url = await _open_pr_if_changed(
            github, "acme", "repo", "agentic/exec-pr-1", task, "exec-pr-1", store, "summary"
        )

        github.commit_changes.assert_not_awaited()
        github.create_pr.assert_not_awaited()
        assert pr_url == ""

    async def test_empty_pr_url_from_adapter_is_not_trusted(self, tmp_path: Path) -> None:
        store, task = _store_with_coding_step(tmp_path, [{"path": "app.py", "content": "print(1)"}])
        github = AsyncMock()
        github.create_pr.return_value = ""

        pr_url = await _open_pr_if_changed(
            github, "acme", "repo", "agentic/exec-pr-1", task, "exec-pr-1", store, "summary"
        )

        assert pr_url == ""

    async def test_no_coding_step_skips_commit_and_pr(self, tmp_path: Path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path / "executions"))
        task = TaskSpec(execution_id="exec-pr-2", title="No coding step", repository_path=".")
        store.create_from_task(task)
        github = AsyncMock()

        pr_url = await _open_pr_if_changed(
            github, "acme", "repo", "agentic/exec-pr-2", task, "exec-pr-2", store, "summary"
        )

        github.commit_changes.assert_not_awaited()
        assert pr_url == ""
