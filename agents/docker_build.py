"""B-001-032 — Docker build/push agent for the fractal sample-service artifact."""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger
from runners.tool_runner import ToolRunner

logger = get_logger(__name__)


class DockerBuildAgent(Agent):
    """Builds (and optionally pushes) a Docker image for the target repository.

    Push only ever runs when `push=True` is explicitly passed at construction
    (wired from a registry-credentials env var by the caller) — never
    implicit, and never attempted locally/dry-run.
    """

    name = "docker_build"

    def __init__(
        self,
        runner: ToolRunner,
        image_repo: str,
        dockerfile_dir: str = "examples/sample-service",
        push: bool = False,
    ) -> None:
        self._runner = runner
        self._image_repo = image_repo
        self._dockerfile_dir = dockerfile_dir
        self._push = push

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {"dockerfile_dir": self._dockerfile_dir, "push": self._push}

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        tag = f"{self._image_repo}:{ctx.execution.execution_id}"

        if ctx.dry_run:
            return {
                "agent_name": self.name,
                "success": True,
                "summary": f"dry-run — skipped docker build for {tag}",
                "image_tag": tag,
                "pushed": False,
            }

        build_result = await self._runner.run(
            "docker",
            ["build", "-t", tag, self._dockerfile_dir],
            cwd=ctx.execution.task.repository_path,
        )

        if build_result.exit_code != 0:
            logger.error("docker_build_failed", tag=tag, exit_code=build_result.exit_code)
            return {
                "agent_name": self.name,
                "success": False,
                "summary": f"docker build failed for {tag}: {build_result.stderr[:500]}",
                "image_tag": tag,
                "pushed": False,
            }

        pushed = False
        if self._push:
            push_result = await self._runner.run("docker", ["push", tag])
            pushed = push_result.exit_code == 0
            if not pushed:
                logger.error("docker_push_failed", tag=tag, exit_code=push_result.exit_code)
                return {
                    "agent_name": self.name,
                    "success": False,
                    "summary": f"docker push failed for {tag}: {push_result.stderr[:500]}",
                    "image_tag": tag,
                    "pushed": False,
                }

        return {
            "agent_name": self.name,
            "success": True,
            "summary": f"built {tag}" + (" and pushed" if pushed else ""),
            "image_tag": tag,
            "pushed": pushed,
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "verified": result.get("success", False),
            "issues": []
            if result.get("success")
            else [result.get("summary", "docker build failed")],
        }
