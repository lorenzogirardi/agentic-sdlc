from __future__ import annotations

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger
from runners.tool_runner import ToolRunner

logger = get_logger(__name__)


class TestPyramidAgent(Agent):
    name = "test_pyramid"

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner

    async def analyze(self, ctx: AgentContext) -> dict:
        repo_path = ctx.execution.task.repository_path
        return {"framework": "pytest", "repo_path": repo_path}

    async def execute(self, ctx: AgentContext) -> dict:
        repo_path = ctx.execution.task.repository_path
        findings: list[dict] = []

        result = await self._runner.run(
            "python", ["-m", "pytest", "--tb=short", "-q"], cwd=repo_path
        )

        passed = 0
        failed = 0
        errors = 0

        if result.exit_code == 0:
            for line in result.stdout.splitlines():
                if "passed" in line.lower():
                    try:
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if "passed" in p.lower():
                                passed = int(parts[i - 1]) if i > 0 else 0
                            if "failed" in p.lower():
                                failed = int(parts[i - 1]) if i > 0 else 0
                    except (ValueError, IndexError):
                        pass

        findings.append(
            {
                "tool": "pytest",
                "exit_code": result.exit_code,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "summary_line": (
                    result.stdout.splitlines()[-1] if result.stdout.splitlines() else "no output"
                ),
            }
        )

        return {
            "agent_name": self.name,
            "success": result.exit_code == 0,
            "summary": f"Tests: {passed} passed, {failed} failed"
            if not result.timed_out
            else "Tests timed out",
            "findings": findings,
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        findings = result.get("findings", [])
        failed = sum(f.get("failed", 0) for f in findings)
        return {
            "verified": result.get("success", False) and failed == 0,
            "issues": [
                f"{f.get('failed', 0)} test(s) failed" for f in findings if f.get("failed", 0) > 0
            ],
        }
