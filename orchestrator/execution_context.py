from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.logging import get_logger
from schemas.execution import ExecutionContext, ExecutionState, StepResult, TaskSpec

logger = get_logger(__name__)

DEFAULT_DATA_DIR = "data/executions"


class ExecutionStore:
    def __init__(self, data_dir: str = DEFAULT_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, execution_id: str) -> Path:
        safe_id = execution_id.replace("/", "_").replace("..", "_")
        return self._data_dir / safe_id / "state.json"

    def save(self, ctx: ExecutionContext) -> None:
        ctx.updated_at = datetime.now(UTC)
        path = self._path(ctx.execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ctx.model_dump_json(indent=2))
        logger.debug("state_saved", execution_id=ctx.execution_id, state=ctx.state)

    def load(self, execution_id: str) -> ExecutionContext | None:
        path = self._path(execution_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return ExecutionContext.model_validate(data)
        except Exception as exc:
            logger.error("state_load_failed", execution_id=execution_id, error=str(exc))
            return None

    def exists(self, execution_id: str) -> bool:
        return self._path(execution_id).exists()

    def add_step(
        self, execution_id: str, step: StepResult, ctx: ExecutionContext | None = None
    ) -> ExecutionContext | None:
        if ctx is None:
            ctx = self.load(execution_id)
        if ctx is None:
            return None
        ctx.steps.append(step)
        self.save(ctx)
        return ctx

    def update_state(
        self, execution_id: str, state: ExecutionState, ctx: ExecutionContext | None = None
    ) -> ExecutionContext | None:
        if ctx is None:
            ctx = self.load(execution_id)
        if ctx is None:
            return None
        ctx.state = state
        self.save(ctx)
        return ctx

    def create_from_task(self, task: TaskSpec) -> ExecutionContext:
        ctx = ExecutionContext(
            execution_id=task.execution_id,
            task=task,
            state=ExecutionState.BACKLOG,
            mode=task.mode,
        )
        self.save(ctx)
        return ctx
