from __future__ import annotations

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger
from runners.tool_runner import ToolRunner

logger = get_logger(__name__)


class LintAgent(Agent):
    name = "lint"

    def __init__(self, runner: ToolRunner, auto_fix: bool = False) -> None:
        self._runner = runner
        self._auto_fix = auto_fix

    async def analyze(self, ctx: AgentContext) -> dict:
        _ = ctx.execution.task.repository_path
        if self._auto_fix:
            return {"tools": ["ruff", "black"], "mode": "fix"}
        return {"tools": ["ruff"], "mode": "check"}

    async def execute(self, ctx: AgentContext) -> dict:
        repo_path = ctx.execution.task.repository_path
        findings: list[dict] = []

        args = ["check", "."] if not self._auto_fix else ["check", "--fix", "."]
        result = await self._runner.run("ruff", args, cwd=repo_path)

        if result.exit_code != 0 and result.stdout:
            findings.append(
                {
                    "tool": "ruff",
                    "output": result.stdout[:2000],
                    "exit_code": result.exit_code,
                }
            )

        return {
            "agent_name": self.name,
            "success": len(findings) == 0 or all(f.get("exit_code", -1) <= 1 for f in findings),
            "summary": f"Lint found {len(findings)} issue group(s)" if findings else "Lint clean",
            "findings": findings,
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        findings = result.get("findings", [])
        return {
            "verified": result.get("success", False),
            "issues": [
                f"Lint issues from {f['tool']}" for f in findings if f.get("exit_code", 0) != 0
            ],
        }
