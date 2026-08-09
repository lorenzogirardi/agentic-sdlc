from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from agents.base import Agent, AgentContext
from schemas.finding import CostEstimate

# Conservative heuristic catalog (EUR/month, rough order-of-magnitude).
# Deliberately minimal: we never invent prices — unknown resources yield
# zero cost with confidence "low" and an explicit assumption note.
RESOURCE_COST_HINTS: dict[str, tuple[float, str]] = {
    "aws_db_instance": (50.0, "RDS instance, small class"),
    "aws_rds_cluster": (200.0, "RDS cluster baseline"),
    "aws_eks_cluster": (73.0, "EKS control plane"),
    "aws_lambda_function": (0.0, "Lambda free tier assumption"),
    "aws_s3_bucket": (1.0, "S3 storage minimal"),
    "aws_nat_gateway": (32.0, "NAT gateway hourly"),
    "aws_lb": (16.0, "ALB hourly"),
    "aws_instance": (8.0, "t3.micro equivalent"),
}

RESOURCE_RE = re.compile(r'resource\s+"(?P<type>[a-z0-9_]+)"\s+"(?P<name>[^"]+)"')


class CostEvalAgent(Agent):
    """Estimate potential cloud cost from IaC — B-001-021."""

    name = "cost_eval"

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        return {"terraform_files": len(list(repo.rglob("*.tf")))}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        estimate = self._estimate(repo)
        return {
            "agent_name": self.name,
            "success": True,
            "summary": (
                f"Estimated monthly cost: {estimate.estimated_monthly_cost:.2f} "
                f"{estimate.currency} (confidence: {estimate.confidence})"
            ),
            "cost": estimate.model_dump(),
            "findings": [
                {
                    "tool": "cost_eval",
                    "severity": "low",
                    "message": f"Cost driver: {d}",
                }
                for d in estimate.cost_drivers
            ],
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        cost = result.get("cost", {})
        warnings = cost.get("warnings", [])
        return {"verified": True, "issues": warnings}

    def _estimate(self, repo: Path) -> CostEstimate:
        total = 0.0
        drivers: list[str] = []
        assumptions: list[str] = []
        warnings: list[str] = []
        unknown_resources = 0

        for tf_file in repo.rglob("*.tf"):
            try:
                content = tf_file.read_text(errors="replace")
            except OSError:
                continue
            for match in RESOURCE_RE.finditer(content):
                rtype = match.group("type")
                rname = match.group("name")
                if rtype in RESOURCE_COST_HINTS:
                    cost, note = RESOURCE_COST_HINTS[rtype]
                    total += cost
                    drivers.append(f"{rtype}.{rname}: ~{cost:.2f} EUR/mo ({note})")
                elif rtype.startswith("aws_"):
                    unknown_resources += 1

        if unknown_resources:
            assumptions.append(
                f"{unknown_resources} AWS resource(s) without cost data — excluded from estimate"
            )
            warnings.append("Estimate is a lower bound; unknown resources not priced")

        if not drivers and not unknown_resources:
            assumptions.append("No cloud resources detected")
            confidence: Literal["low", "medium", "high"] = "high"
        elif unknown_resources > len(drivers):
            confidence = "low"
        elif unknown_resources:
            confidence = "medium"
        else:
            confidence = "medium"

        return CostEstimate(
            currency="EUR",
            estimated_monthly_cost=round(total, 2),
            confidence=confidence,
            assumptions=assumptions,
            cost_drivers=drivers,
            warnings=warnings,
        )
