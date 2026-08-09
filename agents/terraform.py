from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import Agent, AgentContext
from runners.tool_runner import ToolRunner
from schemas.finding import TerraformFinding

SENSITIVE_RESOURCE_PREFIXES = (
    "aws_iam",
    "aws_security_group",
    "aws_s3_bucket",
    "aws_db",
    "aws_rds",
)


class TerraformAgent(Agent):
    """Terraform verification — never runs apply — B-001-018."""

    name = "terraform"

    FORBIDDEN_SUBCOMMANDS = ("apply", "destroy", "import", "state", "taint", "untaint")

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        tf_files = [str(p.relative_to(repo)) for p in repo.rglob("*.tf")]
        return {"terraform_files": tf_files}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        repo = Path(ctx.execution.task.repository_path)
        tf_dirs = {p.parent for p in repo.rglob("*.tf")}

        if not tf_dirs:
            return {
                "agent_name": self.name,
                "success": True,
                "summary": "No Terraform files — skipped",
                "findings": [],
            }

        findings: list[dict[str, Any]] = []

        for tf_dir in tf_dirs:
            for args, tool_label in (
                (["fmt", "-check", "-recursive"], "terraform fmt"),
                (["validate", "-no-color"], "terraform validate"),
            ):
                result = await self._runner.run("terraform", args, cwd=str(tf_dir))
                if result.exit_code == -1:
                    findings.append(
                        {
                            "tool": tool_label,
                            "status": "unavailable",
                            "severity": "low",
                            "message": f"{tool_label} could not run (not installed or blocked)",
                        }
                    )
                    continue
                if result.exit_code != 0:
                    findings.append(
                        {
                            "tool": tool_label,
                            "file": str(tf_dir),
                            "exit_code": result.exit_code,
                            "severity": "medium",
                            "message": result.stderr[:500] or result.stdout[:500],
                        }
                    )

            findings.extend(self._risk_scan(tf_dir, repo))

        blocking = [f for f in findings if f.get("severity") in ("high", "critical")]
        return {
            "agent_name": self.name,
            "success": len(blocking) == 0,
            "summary": (
                f"{len(tf_dirs)} terraform dir(s), {len(findings)} finding(s), "
                f"{len(blocking)} blocking"
            ),
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

    def _risk_scan(self, tf_dir: Path, repo: Path) -> list[dict[str, Any]]:
        import re

        findings: list[dict[str, Any]] = []
        resource_re = re.compile(r'resource\s+"([a-z0-9_]+)"\s+"([^"]+)"')
        for tf_file in tf_dir.glob("*.tf"):
            try:
                content = tf_file.read_text(errors="replace")
            except OSError:
                continue
            rel = str(tf_file.relative_to(repo))

            for match in resource_re.finditer(content):
                rtype = match.group(1)
                if any(rtype.startswith(p) for p in SENSITIVE_RESOURCE_PREFIXES):
                    findings.append(
                        TerraformFinding(
                            file=rel,
                            severity="medium",
                            rule_id="SDLC-TF-001",
                            message=f"Sensitive resource type '{rtype}' detected",
                            resource=rtype,
                            recommendation="Review IAM/networking/storage changes carefully",
                        ).model_dump()
                    )

            if "prevent_destroy" not in content and "aws_db" in content:
                findings.append(
                    TerraformFinding(
                        file=rel,
                        severity="high",
                        rule_id="SDLC-TF-002",
                        message="Database resource without prevent_destroy lifecycle",
                        destructive=True,
                        recommendation="Add lifecycle { prevent_destroy = true }",
                    ).model_dump()
                )
        return findings
