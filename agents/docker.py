from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import Agent, AgentContext
from runners.tool_runner import ToolRunner
from schemas.finding import DockerFinding


class DockerAgent(Agent):
    """Dockerfile and image checks — B-001-019."""

    name = "docker"

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        dockerfiles = [str(p.relative_to(repo)) for p in repo.rglob("Dockerfile*")]
        return {"dockerfiles": dockerfiles}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        findings: list[dict[str, Any]] = []

        dockerfiles = list(repo.rglob("Dockerfile*"))
        if not dockerfiles:
            return {
                "agent_name": self.name,
                "success": True,
                "summary": "No Dockerfile present — skipped",
                "findings": [],
            }

        for df in dockerfiles:
            findings.extend(self._static_checks(df, repo))

            hadolint = await self._runner.run("hadolint", [str(df)], cwd=str(repo))
            if hadolint.exit_code == -1 and not hadolint.blocked:
                findings.append(
                    {
                        "tool": "hadolint",
                        "status": "unavailable",
                        "severity": "low",
                        "message": "hadolint not installed",
                    }
                )
            elif hadolint.exit_code != 0:
                findings.append(
                    {
                        "tool": "hadolint",
                        "file": str(df),
                        "exit_code": hadolint.exit_code,
                        "severity": "medium",
                        "message": hadolint.stdout[:1000],
                    }
                )

        blocking = [f for f in findings if f.get("severity") in ("high", "critical")]
        return {
            "agent_name": self.name,
            "success": len(blocking) == 0,
            "summary": f"{len(findings)} docker finding(s), {len(blocking)} blocking",
            "findings": findings,
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        blocking = [
            f for f in result.get("findings", []) if f.get("severity") in ("high", "critical")
        ]
        return {
            "verified": len(blocking) == 0,
            "issues": [f.get("message", "")[:120] for f in blocking],
        }

    def _static_checks(self, dockerfile: Path, repo: Path) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        try:
            content = dockerfile.read_text(errors="replace")
        except OSError:
            return findings

        lines = content.splitlines()
        rel = str(dockerfile.relative_to(repo))

        has_user = any(line.strip().upper().startswith("USER ") for line in lines)
        if not has_user:
            findings.append(
                DockerFinding(
                    file=rel,
                    severity="high",
                    rule_id="SDLC-DOCKER-001",
                    message="No USER directive — container runs as root",
                    recommendation="Add a non-root USER instruction",
                ).model_dump()
            )

        from_lines = [line for line in lines if line.strip().upper().startswith("FROM ")]
        for i, line in enumerate(from_lines, 1):
            if ":latest" in line or (":" not in line.split()[-1] and " AS " not in line.upper()):
                findings.append(
                    DockerFinding(
                        file=rel,
                        line=i,
                        severity="medium",
                        rule_id="SDLC-DOCKER-002",
                        message="Base image not pinned to a specific version",
                        recommendation="Pin base image with an explicit tag or digest",
                    ).model_dump()
                )

        has_healthcheck = any(line.strip().upper().startswith("HEALTHCHECK") for line in lines)
        if not has_healthcheck:
            findings.append(
                DockerFinding(
                    file=rel,
                    severity="low",
                    rule_id="SDLC-DOCKER-003",
                    message="No HEALTHCHECK instruction",
                    recommendation="Add a HEALTHCHECK for container orchestrators",
                ).model_dump()
            )

        env_lines = [line for line in lines if line.strip().upper().startswith(("ENV ", "ARG "))]
        for line in env_lines:
            if any(k in line.upper() for k in ("SECRET", "PASSWORD", "TOKEN", "KEY=")):
                findings.append(
                    DockerFinding(
                        file=rel,
                        severity="critical",
                        rule_id="SDLC-DOCKER-004",
                        message="Potential secret in ENV/ARG instruction",
                        recommendation="Use build secrets or runtime injection instead",
                    ).model_dump()
                )

        return findings
