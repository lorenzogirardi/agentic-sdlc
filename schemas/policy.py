from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyRule(BaseModel):
    name: str
    value: int | float | bool | str | list[str]
    description: str = ""


class PolicyConfig(BaseModel):
    max_execution_minutes: int = 30
    max_agent_steps: int = 50
    max_retries_per_agent: int = 2
    max_estimated_cost_eur: float = 1.00
    allow_network: bool = False
    allow_terraform_apply: bool = False
    allow_production_deploy: bool = False
    allow_auto_format: bool = False
    max_parallel_agents: int = 4
    require_human_approval_for: list[str] = Field(
        default_factory=lambda: [
            "terraform_apply",
            "merge",
            "production_deploy",
            "secret_access",
        ]
    )
    block_on_security_severity: list[str] = Field(default_factory=lambda: ["critical", "high"])
    allowed_commands: list[str] = Field(
        default_factory=lambda: [
            "git",
            "pytest",
            "npm",
            "pnpm",
            "yarn",
            "go",
            "cargo",
            "terraform",
            "tflint",
            "checkov",
            "trivy",
            "gitleaks",
            "semgrep",
            "docker",
            "hadolint",
            "python",
            "pip",
            "ruff",
            "mypy",
            "coverage",
            "curl",
        ]
    )
    secret_patterns: list[str] = Field(
        default_factory=lambda: [
            r"(?i)(api[_-]?key|token|secret|password|credential)\s*[:=]\s*\S+",
            r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY-----",
            r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}",
            r"sk-[A-Za-z0-9]{32,}",
            r"(AKIA|ASIA)[A-Z0-9]{16}",
        ]
    )
    extra_rules: dict[str, Any] = Field(default_factory=dict)
