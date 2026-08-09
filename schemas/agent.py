from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentPlan(BaseModel):
    agent_name: str
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    estimated_duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_name: str
    success: bool
    summary: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    agent_name: str
    verified: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
