"""B-001-003 — ExecutionStore tests."""

from orchestrator.execution_context import ExecutionStore
from schemas.execution import (
    ExecutionState,
    StepResult,
    StepStatus,
    TaskSpec,
)


class TestExecutionStore:
    def test_create_and_load(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        task = TaskSpec(
            execution_id="test-001",
            title="Test",
            repository_path="./repo",
        )
        ctx = store.create_from_task(task)
        assert ctx.execution_id == "test-001"
        assert ctx.state == ExecutionState.BACKLOG

        loaded = store.load("test-001")
        assert loaded is not None
        assert loaded.execution_id == ctx.execution_id

    def test_load_nonexistent(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        assert store.load("nonexistent") is None

    def test_exists(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        task = TaskSpec(execution_id="exist-test", title="T", repository_path="./r")
        store.create_from_task(task)
        assert store.exists("exist-test") is True
        assert store.exists("missing") is False

    def test_update_state(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        task = TaskSpec(execution_id="state-test", title="T", repository_path="./r")
        store.create_from_task(task)
        store.update_state("state-test", ExecutionState.TRIAGE)
        ctx = store.load("state-test")
        assert ctx is not None
        assert ctx.state == ExecutionState.TRIAGE

    def test_add_step(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        task = TaskSpec(execution_id="step-test", title="T", repository_path="./r")
        store.create_from_task(task)
        step = StepResult(agent_name="test_agent", status=StepStatus.SUCCESS)
        store.add_step("step-test", step)
        ctx = store.load("step-test")
        assert ctx is not None
        assert len(ctx.steps) == 1
        assert ctx.steps[0].agent_name == "test_agent"

    def test_updated_at_changes(self, tmp_path) -> None:
        store = ExecutionStore(data_dir=str(tmp_path))
        task = TaskSpec(execution_id="time-test", title="T", repository_path="./r")
        ctx1 = store.create_from_task(task)
        import time

        time.sleep(0.01)
        store.update_state("time-test", ExecutionState.TRIAGE)
        ctx2 = store.load("time-test")
        assert ctx2 is not None
        assert ctx2.updated_at > ctx1.updated_at
