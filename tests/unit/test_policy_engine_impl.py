"""B-001-006 — PolicyEngine tests."""

from pathlib import Path

import yaml

from orchestrator.policy_engine import PolicyEngine
from schemas.policy import PolicyConfig


class TestPolicyEngine:
    def test_is_allowed_command(self) -> None:
        engine = PolicyEngine(PolicyConfig())
        assert engine.is_allowed_command("git") is True
        assert engine.is_allowed_command("rm") is False

    def test_should_block_critical(self) -> None:
        engine = PolicyEngine(PolicyConfig())
        assert engine.should_block_on_severity("critical") is True
        assert engine.should_block_on_severity("high") is True
        assert engine.should_block_on_severity("medium") is False
        assert engine.should_block_on_severity("low") is False

    def test_requires_human_approval(self) -> None:
        engine = PolicyEngine(PolicyConfig())
        assert engine.requires_human_approval("terraform_apply") is True
        assert engine.requires_human_approval("merge") is True
        assert engine.requires_human_approval("unknown_action") is False

    def test_network_default_blocked(self) -> None:
        engine = PolicyEngine(PolicyConfig())
        assert engine.is_network_allowed() is False

    def test_terraform_apply_default_blocked(self) -> None:
        engine = PolicyEngine(PolicyConfig())
        assert engine.is_terraform_apply_allowed() is False

    def test_within_cost_limit(self) -> None:
        engine = PolicyEngine(PolicyConfig(max_estimated_cost_eur=1.0))
        assert engine.is_within_cost_limit(0.5) is True
        assert engine.is_within_cost_limit(1.0) is True
        assert engine.is_within_cost_limit(1.01) is False

    def test_within_step_limit(self) -> None:
        engine = PolicyEngine(PolicyConfig(max_agent_steps=50))
        assert engine.is_within_agent_step_limit(49) is True
        assert engine.is_within_agent_step_limit(50) is False

    def test_can_retry(self) -> None:
        engine = PolicyEngine(PolicyConfig(max_retries_per_agent=2))
        assert engine.can_retry(0) is True
        assert engine.can_retry(1) is True
        assert engine.can_retry(2) is False

    def test_from_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "policy.yaml"
        yaml_path.write_text(
            yaml.dump(
                {
                    "policies": {
                        "max_execution_minutes": 10,
                        "allowed_commands": ["git", "echo"],
                    }
                }
            )
        )
        engine = PolicyEngine.from_yaml(str(yaml_path))
        assert engine.config.max_execution_minutes == 10
        assert engine.is_allowed_command("git") is True
        assert engine.is_allowed_command("docker") is False

    def test_get_allowed_commands(self) -> None:
        engine = PolicyEngine(PolicyConfig(allowed_commands=["git", "pytest"]))
        cmds = engine.get_allowed_commands()
        assert "git" in cmds
        assert "pytest" in cmds
