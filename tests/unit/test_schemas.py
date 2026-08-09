"""B-001-001 — TaskSpec schema tests (Phase 2a RED)."""

import pytest
from pydantic import ValidationError

from schemas.execution import ExecutionMode, TaskSource, TaskSpec


class TestTaskSpec:
    def test_valid_task_spec_minimal(self) -> None:
        task = TaskSpec(title="Test", repository_path="./repo")
        assert task.title == "Test"
        assert task.repository_path == "./repo"
        assert task.source == TaskSource.YAML
        assert task.mode == ExecutionMode.DRY_RUN
        assert task.execution_id != ""

    def test_task_spec_defaults(self) -> None:
        task = TaskSpec(title="X", repository_path="./repo")
        assert task.description == ""
        assert task.base_branch == "main"
        assert task.acceptance_criteria == []
        assert task.requested_agents == []

    def test_task_spec_missing_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskSpec(repository_path="./repo")

    def test_task_spec_missing_repo_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskSpec(title="X")

    def test_task_spec_full(self) -> None:
        task = TaskSpec(
            title="Add feature",
            description="Add a new endpoint",
            repository_path="./repo",
            base_branch="develop",
            acceptance_criteria=["HTTP 200", "coverage > 80%"],
            requested_agents=["test_pyramid", "security"],
            mode=ExecutionMode.PR,
        )
        assert task.description == "Add a new endpoint"
        assert task.base_branch == "develop"
        assert len(task.acceptance_criteria) == 2
        assert len(task.requested_agents) == 2
        assert task.mode == ExecutionMode.PR

    def test_execution_id_is_unique(self) -> None:
        t1 = TaskSpec(title="A", repository_path="./a")
        t2 = TaskSpec(title="B", repository_path="./b")
        assert t1.execution_id != t2.execution_id

    def test_metadata_field(self) -> None:
        task = TaskSpec(
            title="X",
            repository_path="./repo",
            metadata={"trello_card_id": "abc123", "priority": "high"},
        )
        assert task.metadata["trello_card_id"] == "abc123"
