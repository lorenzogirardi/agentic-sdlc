from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ExecutionMode(StrEnum):
    DRY_RUN = "dry_run"
    PR = "pr"
    APPROVAL_REQUIRED = "approval_required"


class ExecutionState(StrEnum):
    BACKLOG = "BACKLOG"
    TRIAGE = "TRIAGE"
    SPECIFIED = "SPECIFIED"
    PLANNED = "PLANNED"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DONE = "DONE"
    FIX_REQUIRED = "FIX_REQUIRED"
    BLOCKED = "BLOCKED"


class TaskSource(StrEnum):
    YAML = "yaml"
    TRELLO = "trello"
    GITHUB = "github"


class TaskSpec(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    source: TaskSource = TaskSource.YAML
    title: str
    description: str = ""
    repository_path: str
    base_branch: str = "main"
    acceptance_criteria: list[str] = Field(default_factory=list)
    requested_agents: list[str] = Field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class StepResult(BaseModel):
    agent_name: str
    status: StepStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float = 0.0
    error: str | None = None
    retry_count: int = 0
    output: dict[str, Any] | None = None


class ExecutionContext(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    task: TaskSpec
    state: ExecutionState = ExecutionState.BACKLOG
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    branch_name: str | None = None
    pr_url: str | None = None
    steps: list[StepResult] = Field(default_factory=list)
    dag: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionReport(BaseModel):
    execution_id: str
    task_title: str
    final_state: ExecutionState
    verdict: Literal["PASS", "PASS_WITH_WARNINGS", "BLOCKED", "REQUIRES_HUMAN_APPROVAL"]
    summary: str
    total_duration_ms: float = 0.0
    total_agent_steps: int = 0
    total_tool_calls: int = 0
    estimated_cost_eur: float = 0.0
    token_usage: dict[str, int] = Field(default_factory=dict)
    agent_results: list[StepResult] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)
