from __future__ import annotations

from pathlib import Path

import yaml

from schemas.policy import PolicyConfig


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    @classmethod
    def from_yaml(cls, path: str | Path) -> PolicyEngine:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        policies = raw.get("policies", {})
        config = PolicyConfig(
            max_execution_minutes=policies.get("max_execution_minutes", 30),
            max_agent_steps=policies.get("max_agent_steps", 50),
            max_retries_per_agent=policies.get("max_retries_per_agent", 2),
            max_estimated_cost_eur=policies.get("max_estimated_cost_eur", 1.00),
            allow_network=policies.get("allow_network", False),
            allow_terraform_apply=policies.get("allow_terraform_apply", False),
            allow_production_deploy=policies.get("allow_production_deploy", False),
            max_parallel_agents=policies.get("max_parallel_agents", 4),
            require_human_approval_for=policies.get(
                "require_human_approval_for",
                ["terraform_apply", "merge", "production_deploy", "secret_access"],
            ),
            block_on_security_severity=policies.get(
                "block_on_security_severity", ["critical", "high"]
            ),
            allowed_commands=policies.get("allowed_commands", []),
        )
        return cls(config)

    def is_allowed_command(self, command: str) -> bool:
        return command in self.config.allowed_commands

    def should_block_on_severity(self, severity: str) -> bool:
        return severity in self.config.block_on_security_severity

    def requires_human_approval(self, action: str) -> bool:
        return action in self.config.require_human_approval_for

    def is_network_allowed(self) -> bool:
        return self.config.allow_network

    def is_terraform_apply_allowed(self) -> bool:
        return self.config.allow_terraform_apply

    def is_production_deploy_allowed(self) -> bool:
        return self.config.allow_production_deploy

    def is_within_cost_limit(self, estimated_cost_eur: float) -> bool:
        return estimated_cost_eur <= self.config.max_estimated_cost_eur

    def is_within_agent_step_limit(self, steps: int) -> bool:
        return steps < self.config.max_agent_steps

    def can_retry(self, current_retries: int) -> bool:
        return current_retries < self.config.max_retries_per_agent

    def get_allowed_commands(self) -> list[str]:
        return list(self.config.allowed_commands)
