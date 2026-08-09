from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import Agent, AgentContext
from runners.tool_runner import ToolRunner


class CodeQualityAgent(Agent):
    """Language-aware code quality checks: typing, complexity, smells."""

    name = "code_quality"

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {"repo": ctx.execution.task.repository_path}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo_path = ctx.execution.task.repository_path
        findings: list[dict[str, Any]] = []

        if not (Path(repo_path) / "pyproject.toml").exists() and not list(
            Path(repo_path).rglob("*.py")
        ):
            return {
                "agent_name": self.name,
                "success": True,
                "summary": "No Python sources — quality checks not applicable",
                "findings": [],
            }

        mypy_result = await self._runner.run(
            "python", ["-m", "mypy", "--ignore-missing-imports", "."], cwd=repo_path
        )
        findings.append(
            {
                "tool": "mypy",
                "exit_code": mypy_result.exit_code,
                "category": "typing",
                "severity": "medium" if mypy_result.exit_code != 0 else "low",
                "message": mypy_result.stdout[-500:] if mypy_result.stdout else "",
            }
        )

        large_files = [str(p) for p in Path(repo_path).rglob("*.py") if p.stat().st_size > 50_000]
        for f in large_files:
            findings.append(
                {
                    "tool": "size_check",
                    "file": f,
                    "category": "maintainability",
                    "severity": "low",
                    "message": "File exceeds 50KB — consider splitting",
                }
            )

        failures = [f for f in findings if f.get("exit_code", 0) not in (0,)]
        return {
            "agent_name": self.name,
            "success": len(failures) == 0,
            "summary": f"{len(findings)} quality check(s), {len(failures)} failing",
            "findings": findings,
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        failing = [f for f in result.get("findings", []) if f.get("exit_code", 0) != 0]
        return {
            "verified": len(failing) == 0,
            "issues": [f"{f['tool']} reported errors" for f in failing],
        }
