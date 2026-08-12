from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from agents.base import Agent, AgentContext
from orchestrator.logging import get_logger

logger = get_logger(__name__)


class FileChange(BaseModel):
    path: str
    content: str
    rationale: str = ""


class CodingResult(BaseModel):
    changes: list[FileChange] = Field(default_factory=list)


class CodingAgent(Agent):
    name = "coding"
    FORBIDDEN_PATH_PARTS = (".env", "secret", "credential", ".git/", "id_rsa", ".pem")
    READABLE_SUFFIXES = (".py", ".yaml", ".yml", ".toml", ".txt", ".md", ".json")
    MAX_CONTEXT_BYTES = 20_000

    def __init__(self, opencode_adapter: Any = None) -> None:
        self._opencode = opencode_adapter
        self.feedback: str = ""

    async def analyze(self, ctx: AgentContext) -> dict[str, Any]:
        return {
            "repository": ctx.execution.task.repository_path,
            "dry_run": ctx.dry_run,
            "llm_available": self._opencode is not None,
        }

    async def execute(self, ctx: AgentContext) -> dict[str, Any]:
        task = ctx.execution.task
        fb = getattr(self, "feedback", "")

        if self._opencode is None:
            return {
                "agent_name": self.name,
                "success": True,
                "summary": "No LLM configured — coding agent skipped",
                "changes": [],
                "dry_run": True,
            }

        existing_files = self._read_repo_context(task.repository_path)

        try:
            result = await self._opencode.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior software engineer. Given a task and the "
                            "CURRENT content of the relevant repository files, produce "
                            "the minimal file changes to satisfy the task. "
                            "Extend the existing code shown below — match its framework, "
                            "style, and response shapes. Do not rewrite working code to a "
                            "different framework or library unless the task explicitly "
                            "asks for it. "
                            "Return valid JSON with 'changes' array. "
                            "Each change has: path, content (FULL file), rationale. "
                            "Never modify .env, secrets, credentials."
                            + (f"\n\nFix these issues:\n{fb}" if fb else "")
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "title": task.title,
                                "description": task.description,
                                "acceptance_criteria": task.acceptance_criteria,
                                "existing_files": existing_files,
                            }
                        ),
                    },
                ],
                response_schema=CodingResult,
            )
        except Exception as exc:
            logger.warning("coding_llm_failed", error=str(exc))
            return {"agent_name": self.name, "success": False, "error": str(exc), "changes": []}

        self.feedback = ""
        raw_changes = result.get("changes", [])
        if not raw_changes and "raw_output" in result:
            raw_changes = _extract_json_changes(result["raw_output"])

        changes = [
            {
                "path": c.get("path", ""),
                "content": c.get("content", ""),
                "rationale": c.get("rationale", ""),
            }
            for c in raw_changes
        ]
        safe = [c for c in changes if self._is_safe_path(c.get("path", ""))]
        rejected = [c for c in changes if not self._is_safe_path(c.get("path", ""))]

        if rejected:
            logger.warning("coding_rejected", count=len(rejected))
        if not changes:
            logger.warning("coding_no_changes")

        if not ctx.dry_run:
            self._apply_changes(ctx.execution.task.repository_path, safe)

        return {
            "agent_name": self.name,
            "success": True,
            "summary": f"{len(safe)} change(s), {len(rejected)} rejected",
            "changes": safe,
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
        return not any(part in path.lower() for part in self.FORBIDDEN_PATH_PARTS)

    def _read_repo_context(self, repository_path: str) -> str:
        """Snapshot of existing source files, so the LLM extends real code
        instead of inventing a fresh implementation (and picking a different
        framework) from scratch."""
        root = Path(repository_path)
        if not root.is_dir():
            return ""

        parts: list[str] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in self.READABLE_SUFFIXES:
                continue
            rel = str(path.relative_to(root))
            if not self._is_safe_path(rel):
                continue
            try:
                content = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if total + len(content) > self.MAX_CONTEXT_BYTES:
                continue
            parts.append(f"--- {rel} ---\n{content}")
            total += len(content)

        return "\n\n".join(parts)

    def _apply_changes(self, repo_path: str, changes: list[dict[str, Any]]) -> None:
        root = Path(repo_path).resolve()
        for change in changes:
            rel = change.get("path", "")
            content = change.get("content", "")
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)):
                logger.warning("coding_path_escape", path=rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


def _extract_json_changes(raw: str) -> list[dict[str, Any]]:
    json_match = re.search(r"\{[\s\S]*\"changes\"[\s\S]*\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return cast(list[dict[str, Any]], data.get("changes", []))
        except (json.JSONDecodeError, TypeError):
            pass
    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw)
    for block in code_blocks:
        try:
            data = json.loads(block.strip())
            if "changes" in data:
                return cast(list[dict[str, Any]], data["changes"])
        except (json.JSONDecodeError, TypeError):
            continue
    return []
