from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agents.base import Agent, AgentContext


class ObservabilityAgent(Agent):
    """Check health/readiness endpoints, metrics, logging, tracing — B-001-020.

    Suggestion-only: never modifies code.
    """

    name = "observability"

    HEALTH_PATTERNS = re.compile(r'@app\.(get|post)\(\s*["\'](/health|/healthz|/livez)', re.I)
    READINESS_PATTERNS = re.compile(r'["\'](/ready|/readiness|/readyz)["\']', re.I)
    METRICS_PATTERNS = re.compile(r"(prometheus_client|/metrics|Counter\(|Histogram\()", re.I)
    TRACING_PATTERNS = re.compile(r"(opentelemetry|TracerProvider|start_as_current_span)", re.I)
    LOGGING_PATTERNS = re.compile(r"(structlog|logging\.getLogger|get_logger)", re.I)

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {"repo": ctx.execution.task.repository_path}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        checks = {
            "health_endpoint": False,
            "readiness_endpoint": False,
            "prometheus_metrics": False,
            "structured_logging": False,
            "otel_tracing": False,
        }

        for py_file in repo.rglob("*.py"):
            try:
                content = py_file.read_text(errors="replace")
            except OSError:
                continue
            if self.HEALTH_PATTERNS.search(content):
                checks["health_endpoint"] = True
            if self.READINESS_PATTERNS.search(content):
                checks["readiness_endpoint"] = True
            if self.METRICS_PATTERNS.search(content):
                checks["prometheus_metrics"] = True
            if self.LOGGING_PATTERNS.search(content):
                checks["structured_logging"] = True
            if self.TRACING_PATTERNS.search(content):
                checks["otel_tracing"] = True

        suggestions = [
            f"Missing: {name.replace('_', ' ')}" for name, ok in checks.items() if not ok
        ]

        return {
            "agent_name": self.name,
            "success": True,
            "summary": (f"Observability: {sum(checks.values())}/{len(checks)} checks present"),
            "checks": checks,
            "suggestions": suggestions,
            "findings": [
                {"tool": "observability", "severity": "low", "message": s} for s in suggestions
            ],
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        checks = result.get("checks", {})
        missing = [k for k, v in checks.items() if not v]
        return {
            "verified": True,  # suggestions only — never blocking
            "issues": [],
            "suggestions": [f"Consider adding {m.replace('_', ' ')}" for m in missing],
        }
