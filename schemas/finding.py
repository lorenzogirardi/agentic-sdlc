from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class SecurityFinding(BaseModel):
    id: str
    severity: Severity
    file: str = ""
    line: int = 0
    message: str
    recommendation: str = ""
    blocking: bool = False
    tool: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class LintIssue(BaseModel):
    file: str
    line: int = 0
    column: int = 0
    severity: Severity = "low"
    rule: str = ""
    message: str
    fixable: bool = False


class QualityIssue(BaseModel):
    file: str = ""
    line: int = 0
    category: str
    severity: Severity = "low"
    message: str
    metric: str = ""
    value: float = 0.0
    threshold: float = 0.0


class CostEstimate(BaseModel):
    currency: str = "EUR"
    estimated_monthly_cost: float = 0.0
    confidence: Literal["low", "medium", "high"] = "low"
    assumptions: list[str] = Field(default_factory=list)
    cost_drivers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TerraformFinding(BaseModel):
    file: str
    line: int = 0
    severity: Severity
    rule_id: str = ""
    message: str
    resource: str = ""
    destructive: bool = False
    recommendation: str = ""


class DockerFinding(BaseModel):
    file: str = "Dockerfile"
    line: int = 0
    severity: Severity
    rule_id: str = ""
    message: str
    recommendation: str = ""
