"""B-001-007 — Tool Runner tests (Phase 2a RED)."""

import re

from schemas.policy import PolicyConfig


class TestToolRunner:
    def test_secret_pattern_matches_api_key(self) -> None:
        policy = PolicyConfig()
        pattern = policy.secret_patterns[0]
        assert re.search(pattern, "api_key=sk-abc123secret456")
        assert re.search(pattern, "API_KEY: my-secret-value")

    def test_secret_pattern_matches_private_key_header(self) -> None:
        policy = PolicyConfig()
        pattern = policy.secret_patterns[1]
        assert re.search(pattern, "-----BEGIN RSA PRIVATE KEY-----")

    def test_secret_pattern_matches_github_token(self) -> None:
        policy = PolicyConfig()
        pattern = policy.secret_patterns[2]
        assert re.search(pattern, "ghp_1234567890abcdef1234567890abcdef123456")

    def test_command_in_allowlist(self) -> None:
        policy = PolicyConfig()
        for cmd in ["git", "pytest", "docker"]:
            assert cmd in policy.allowed_commands

    def test_command_not_in_allowlist(self) -> None:
        policy = PolicyConfig()
        for cmd in ["rm", "sudo", "chmod", "kill", "shutdown"]:
            assert cmd not in policy.allowed_commands
