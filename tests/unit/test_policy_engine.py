"""B-001-006 — Policy Engine tests (Phase 2a RED)."""

import pytest

from schemas.policy import PolicyConfig


class TestPolicyConfig:
    def test_default_policy_values(self) -> None:
        policy = PolicyConfig()
        assert policy.max_execution_minutes == 30
        assert policy.max_agent_steps == 50
        assert policy.max_retries_per_agent == 2
        assert policy.max_estimated_cost_eur == 1.00
        assert policy.allow_network is False
        assert policy.allow_terraform_apply is False
        assert policy.allow_production_deploy is False

    def test_block_on_security_severity_defaults(self) -> None:
        policy = PolicyConfig()
        assert "critical" in policy.block_on_security_severity
        assert "high" in policy.block_on_security_severity
        assert "low" not in policy.block_on_security_severity

    def test_require_human_approval_defaults(self) -> None:
        policy = PolicyConfig()
        assert "terraform_apply" in policy.require_human_approval_for
        assert "merge" in policy.require_human_approval_for
        assert "production_deploy" in policy.require_human_approval_for

    def test_allowed_commands_contains_base_tools(self) -> None:
        policy = PolicyConfig()
        assert "git" in policy.allowed_commands
        assert "pytest" in policy.allowed_commands
        assert "docker" in policy.allowed_commands

    def test_command_not_allowed(self) -> None:
        policy = PolicyConfig()
        assert "rm" not in policy.allowed_commands
        assert "sudo" not in policy.allowed_commands
        assert "chmod" not in policy.allowed_commands

    def test_secret_patterns(self) -> None:
        import re

        policy = PolicyConfig()
        for pattern in policy.secret_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                pytest.fail(f"Invalid regex pattern {pattern!r}: {exc}")

    def test_overrides_via_init(self) -> None:
        policy = PolicyConfig(
            max_execution_minutes=10,
            allow_network=True,
            allowed_commands=["git", "echo"],
        )
        assert policy.max_execution_minutes == 10
        assert policy.allow_network is True
        assert policy.allowed_commands == ["git", "echo"]


class TestPolicyIsDeterministic:
    def test_same_config_same_output(self) -> None:
        p1 = PolicyConfig()
        p2 = PolicyConfig()
        assert p1.max_execution_minutes == p2.max_execution_minutes
        assert p1.allow_terraform_apply == p2.allow_terraform_apply
        assert p1.block_on_security_severity == p2.block_on_security_severity
