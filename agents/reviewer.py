from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger

logger = get_logger(__name__)

Verdict = Literal["PASS", "PASS_WITH_WARNINGS", "BLOCKED", "REQUIRES_HUMAN_APPROVAL"]


class ReviewerAgent(Agent):
    name = "reviewer"

    async def analyze(self, ctx: AgentContext) -> dict:
        return {"mode": "aggregate", "steps_count": len(ctx.execution.steps)}

    async def execute(self, ctx: AgentContext) -> dict:
        steps = ctx.execution.steps
        task = ctx.execution.task

        failed_steps = [s for s in steps if s.status.value.upper() in ("FAILED", "FAILURE")]
        warnings: list[str] = []
        blocker_count = 0

        for step in steps:
            if step.status.value.upper() in ("FAILED", "FAILURE"):
                warnings.append(
                    f"[{step.agent_name}] Step failed: {step.error or 'no error detail'}"
                )

            output = step.output or {}
            findings = output.get("findings", [])
            for f in findings:
                severity = f.get("severity", "")
                exit_code = f.get("exit_code", 0)

                if severity in ("critical", "high"):
                    blocker_count += 1
                    warnings.append(
                        f"[{step.agent_name}] Critical finding: "
                        f"{f.get('message', f.get('tool', 'unknown'))}"
                    )
                elif severity == "medium":
                    warnings.append(f"[{step.agent_name}] Warning from {f.get('tool', 'unknown')}")
                elif exit_code != 0:
                    warnings.append(
                        f"[{step.agent_name}] Tool {f.get('tool', 'unknown')} "
                        f"exited with code {exit_code}"
                    )

        verdict: Verdict
        if blocker_count > 0:
            verdict = "BLOCKED"
        elif failed_steps:
            verdict = "REQUIRES_HUMAN_APPROVAL"
        elif warnings:
            verdict = "PASS_WITH_WARNINGS"
        else:
            verdict = "PASS"

        report = {
            "execution_id": ctx.execution.execution_id,
            "task_title": task.title,
            "final_state": ctx.execution.state,
            "verdict": verdict,
            "summary": f"Review complete: {verdict}. {len(steps)} agents executed.",
            "total_duration_ms": (
                (ctx.execution.finished_at - ctx.execution.started_at).total_seconds() * 1000
                if ctx.execution.started_at and ctx.execution.finished_at
                else 0
            ),
            "total_agent_steps": len(steps),
            "agent_results": [
                {
                    "agent_name": s.agent_name,
                    "status": s.status,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in steps
            ],
            "warnings": warnings,
            "errors": [s.error for s in failed_steps if s.error],
            "created_at": datetime.now(UTC).isoformat(),
        }

        return {
            "agent_name": self.name,
            "success": verdict != "BLOCKED",
            "summary": f"Verdict: {verdict}",
            "verdict": verdict,
            "report": report,
            "findings": warnings,
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        verdict = result.get("verdict", "UNKNOWN")
        return {
            "verified": verdict in ("PASS", "PASS_WITH_WARNINGS"),
            "issues": [f"Blocked by {result.get('findings', [])}"]
            if verdict in ("BLOCKED",)
            else [],
        }
