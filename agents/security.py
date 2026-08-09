from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger
from runners.tool_runner import ToolRunner

logger = get_logger(__name__)

SECURITY_TOOLS = [
    {"name": "gitleaks", "args": ["detect", "--no-git", "--verbose"]},
    {"name": "semgrep", "args": ["--config", "auto", "--quiet"]},
]


class SecurityAgent(Agent):
    name = "security"

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner

    async def analyze(self, ctx: AgentContext) -> dict:
        return {"tools_configured": [t["name"] for t in SECURITY_TOOLS]}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo_path = ctx.execution.task.repository_path
        findings: list[dict[str, Any]] = []

        for tool_cfg in SECURITY_TOOLS:
            tool_name: str = str(tool_cfg["name"])
            args: list[str] = [str(a) for a in tool_cfg["args"]]

            if not self._runner.is_allowed(tool_name):
                findings.append(
                    {
                        "tool": tool_name,
                        "status": "skipped",
                        "reason": "Tool not in allowlist or not installed",
                    }
                )
                continue

            result = await self._runner.run(tool_name, args, cwd=repo_path)

            severity = "low"
            if result.exit_code != 0:
                severity = "high" if "critical" in result.stdout.lower() else "medium"

            findings.append(
                {
                    "tool": tool_name,
                    "exit_code": result.exit_code,
                    "severity": severity,
                    "output_snippet": result.stdout[:1000] if result.stdout else "",
                }
            )

        has_critical = any(f.get("severity") in ("high", "critical") for f in findings)
        return {
            "agent_name": self.name,
            "success": not has_critical,
            "summary": f"Security scan: {len(findings)} tool(s) run, "
            f"exit codes: {[f.get('exit_code') for f in findings]}",
            "findings": findings,
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        findings = result.get("findings", [])
        critical = [f for f in findings if f.get("severity") in ("high", "critical")]
        return {
            "verified": len(critical) == 0,
            "issues": [f"Critical finding from {f['tool']}" for f in critical],
        }
