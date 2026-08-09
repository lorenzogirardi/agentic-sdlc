from __future__ import annotations

import json
from typing import Any

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger

logger = get_logger(__name__)


class CodingAgent(Agent):
    """Implements the task on a dedicated branch via LLM-generated diffs.

    Guardrails:
    - Only modifies files returned by the LLM inside the repository tree.
    - Never touches sensitive files (.env, secrets, CI credentials).
    - No merge — only file modifications on the working tree (or dry-run preview).
    """

    name = "coding"

    FORBIDDEN_PATH_PARTS = (".env", "secret", "credential", ".git/", "id_rsa", ".pem")

    def __init__(self, opencode_adapter: Any = None) -> None:
        self._opencode = opencode_adapter

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {
            "repository": ctx.execution.task.repository_path,
            "dry_run": ctx.dry_run,
            "llm_available": self._opencode is not None,
        }

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        task = ctx.execution.task

        if self._opencode is None:
            return {
                "agent_name": self.name,
                "success": True,
                "summary": "No LLM configured — coding agent skipped (plan-only mode)",
                "changes": [],
                "dry_run": True,
            }

        try:
            result = await self._opencode.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior software engineer. Given a task, produce "
                            "the minimal set of file changes needed. Return JSON with "
                            "'changes': [{path, content, rationale}]. Never modify "
                            "secrets, CI credentials, or dependency files without "
                            "explicit justification in 'rationale'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "title": task.title,
                                "description": task.description,
                                "acceptance_criteria": task.acceptance_criteria,
                            }
                        ),
                    },
                ],
            )
        except Exception as exc:
            return {
                "agent_name": self.name,
                "success": False,
                "error": str(exc),
                "changes": [],
            }

        changes = result.get("changes", [])
        safe_changes = [c for c in changes if self._is_safe_path(c.get("path", ""))]
        rejected = [c for c in changes if not self._is_safe_path(c.get("path", ""))]

        if rejected:
            logger.warning("coding_rejected_paths", count=len(rejected))

        if not ctx.dry_run:
            self._apply_changes(ctx.execution.task.repository_path, safe_changes)

        return {
            "agent_name": self.name,
            "success": True,
            "summary": f"{len(safe_changes)} change(s) prepared, {len(rejected)} rejected",
            "changes": safe_changes,
            "rejected": [c.get("path") for c in rejected],
            "dry_run": ctx.dry_run,
        }

    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]:
        rejected = result.get("rejected", [])
        return {
            "verified": len(rejected) == 0,
            "issues": [f"Rejected unsafe path: {p}" for p in rejected],
        }

    def _is_safe_path(self, path: str) -> bool:
        lowered = path.lower()
        return not any(part in lowered for part in self.FORBIDDEN_PATH_PARTS)

    def _apply_changes(self, repo_path: str, changes: list[dict[str, Any]]) -> None:
        from pathlib import Path

        root = Path(repo_path).resolve()
        for change in changes:
            rel = change.get("path", "")
            content = change.get("content", "")
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)):
                logger.warning("coding_path_escape_blocked", path=rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
