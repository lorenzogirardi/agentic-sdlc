"""B-001-009 — GitHub Adapter tests."""

from integrations.github_adapter import DryRunGitHubAdapter, GitHubRESTAdapter


class TestDryRunAdapter:
    async def test_create_branch(self) -> None:
        adapter = DryRunGitHubAdapter()
        branch = await adapter.create_branch("owner", "repo", "feat/test", "main")
        assert branch == "feat/test"

    async def test_commit_changes(self) -> None:
        adapter = DryRunGitHubAdapter()
        sha = await adapter.commit_changes(
            "owner",
            "repo",
            "feat/test",
            "test commit",
            {"file.py": "print('hello')"},
        )
        assert sha == "dry-run-commit"

    async def test_create_pr(self) -> None:
        adapter = DryRunGitHubAdapter()
        url = await adapter.create_pr(
            "owner",
            "repo",
            "feat/test",
            "main",
            "Test PR",
            "Body",
        )
        assert "dry-run" in url

    async def test_add_pr_comment(self) -> None:
        adapter = DryRunGitHubAdapter()
        await adapter.add_pr_comment("owner", "repo", 1, "hello")

    async def test_get_repo_structure(self) -> None:
        adapter = DryRunGitHubAdapter()
        items = await adapter.get_repo_structure("owner", "repo")
        assert len(items) >= 1


class TestRESTAdapter:
    def test_init_with_token(self) -> None:
        adapter = GitHubRESTAdapter(token="ghp_test123")
        assert adapter.token == "ghp_test123"

    def test_init_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "env_token")
        adapter = GitHubRESTAdapter()
        assert adapter.token == "env_token"

    def test_dry_run_mode(self) -> None:
        adapter = GitHubRESTAdapter(token="test", dry_run=True)
        assert adapter._dry_run is True

    def test_auth_headers(self) -> None:
        adapter = GitHubRESTAdapter(token="test_token")
        headers = adapter._auth_headers()
        assert "Bearer test_token" in headers["Authorization"]
