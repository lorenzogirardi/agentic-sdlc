from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass

from orchestrator.logging import get_logger

logger = get_logger(__name__)

REDACTED_MARKER = "[REDACTED]"
MAX_OUTPUT_BYTES = 512 * 1024  # 512 KB
DEFAULT_TIMEOUT_SEC = 120


@dataclass
class ToolResult:
    command: str
    args: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    blocked: bool = False
    block_reason: str = ""


class ToolRunner:
    def __init__(
        self,
        allowed_commands: list[str],
        secret_patterns: list[str] | None = None,
        default_timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._allowed = set(allowed_commands)
        self._secret_re = [re.compile(p) for p in (secret_patterns or [])]
        self._default_timeout = default_timeout

    def is_allowed(self, command: str) -> bool:
        return command in self._allowed

    def redact(self, text: str) -> str:
        result = text
        for pattern in self._secret_re:
            result = pattern.sub(REDACTED_MARKER, result)
        return result

    def _redact_env(self, env_vars: dict[str, str]) -> dict[str, str]:
        return {k: self.redact(v) for k, v in env_vars.items()}

    async def run(
        self,
        command: str,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ToolResult:
        if not self.is_allowed(command):
            msg = f"Command '{command}' is not in the allowlist"
            logger.warning("tool_blocked", command=command, reason=msg)
            return ToolResult(
                command=command,
                args=args,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                blocked=True,
                block_reason=msg,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        full_args = [command, *args]

        proc_env: dict[str, str] | None = None
        if env is not None:
            merged = os.environ.copy()
            merged.update(env)
            proc_env = merged

        logger.debug("tool_run", command=command, args=args, cwd=cwd)

        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *full_args,
                cwd=cwd,
                env=proc_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("tool_timeout", command=command, timeout=effective_timeout)
            return ToolResult(
                command=command,
                args=args,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                timed_out=True,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("tool_error", command=command, error=str(exc))
            return ToolResult(
                command=command,
                args=args,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = (time.perf_counter() - start) * 1000

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        stdout = self._truncate(stdout)
        stderr = self._truncate(stderr)
        stdout = self.redact(stdout)
        stderr = self.redact(stderr)

        logger.debug(
            "tool_done",
            command=command,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
        )

        return ToolResult(
            command=command,
            args=args,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _truncate(text: str) -> str:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > MAX_OUTPUT_BYTES:
            return (
                encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
                + "\n[OUTPUT TRUNCATED]"
            )
        return text
