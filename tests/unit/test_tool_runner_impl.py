"""B-001-007 — ToolRunner implementation tests."""

import pytest

from runners.tool_runner import REDACTED_MARKER, ToolRunner


class TestToolRunner:
    @pytest.fixture
    def runner(self) -> ToolRunner:
        return ToolRunner(
            allowed_commands=["git", "echo", "python", "ls"],
            secret_patterns=[
                r"secret_\d+",
            ],
        )

    def test_is_allowed_true(self, runner: ToolRunner) -> None:
        for cmd in ("git", "echo", "python", "ls"):
            assert runner.is_allowed(cmd) is True

    def test_is_allowed_false(self, runner: ToolRunner) -> None:
        for cmd in ("rm", "sudo", "curl", "wget"):
            assert runner.is_allowed(cmd) is False

    def test_redact_replaces_secret(self, runner: ToolRunner) -> None:
        text = "api_key=secret_12345 and password=secret_67890"
        redacted = runner.redact(text)
        assert "secret_12345" not in redacted
        assert "secret_67890" not in redacted
        assert REDACTED_MARKER in redacted

    def test_redact_no_secret_unchanged(self, runner: ToolRunner) -> None:
        text = "hello world"
        assert runner.redact(text) == text

    async def test_blocked_command(self, runner: ToolRunner) -> None:
        result = await runner.run("rm", ["-rf", "/"])
        assert result.blocked is True
        assert "not in the allowlist" in result.block_reason
        assert result.exit_code == -1

    async def test_allowed_command(self, runner: ToolRunner) -> None:
        result = await runner.run("echo", ["hello"])
        assert result.blocked is False
        assert result.timed_out is False
        assert "hello" in result.stdout

    async def test_command_timeout(self) -> None:
        runner = ToolRunner(allowed_commands=["sleep"], default_timeout=1)
        result = await runner.run("sleep", ["5"])
        assert result.timed_out is True

    async def test_command_output_truncation(self, runner: ToolRunner) -> None:
        result = await runner.run("python", ["-c", "print('A' * 1000)"])
        assert "A" * 1000 in result.stdout or "[OUTPUT TRUNCATED]" in result.stdout

    def test_redact_env_vars(self, runner: ToolRunner) -> None:
        env = {"API_KEY": "secret_999", "PUBLIC": "visible"}
        redacted = runner._redact_env(env)
        assert "secret_999" not in redacted["API_KEY"]
        assert redacted["PUBLIC"] == "visible"
