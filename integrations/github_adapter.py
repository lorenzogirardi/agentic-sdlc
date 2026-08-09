from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

from orchestrator.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.github.com"


class GitHubAdapterError(Exception):
    pass


class GitHubPermissionError(GitHubAdapterError):
    pass


class GitHubAdapter(ABC):
    @abstractmethod
    async def create_branch(
        self, owner: str, repo: str, branch_name: str, base_branch: str
    ) -> str: ...

    @abstractmethod
    async def commit_changes(
        self, owner: str, repo: str, branch_name: str, message: str, files: dict[str, str]
    ) -> str: ...

    @abstractmethod
    async def create_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str: ...

    @abstractmethod
    async def add_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment: str,
    ) -> None: ...

    @abstractmethod
    async def get_repo_structure(
        self,
        owner: str,
        repo: str,
        path: str = "",
    ) -> list[dict[str, Any]]: ...


class GitHubRESTAdapter(GitHubAdapter):
    def __init__(
        self,
        token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        dry_run: bool = False,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self._base_url = base_url.rstrip("/")
        self._dry_run = dry_run
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._auth_headers(),
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if self._dry_run:
            logger.info("github_dry_run", method=method, path=path)
            return httpx.Response(200, json={"dry_run": True, "path": path, "method": method})

        response = await self.client.request(method, path, json=json_data)
        if response.status_code in (401, 403):
            raise GitHubPermissionError(
                f"Permission denied ({response.status_code}): {response.text[:200]}"
            )
        elif response.status_code >= 400:
            logger.error(
                "github_api_error",
                method=method,
                path=path,
                status=response.status_code,
                body=response.text[:200],
            )
        return response

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_branch: str,
    ) -> str:
        ref_path = f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}"
        ref_resp = await self._request("GET", ref_path)
        if ref_resp.status_code != 200 and not self._dry_run:
            raise GitHubAdapterError(
                f"Base branch '{base_branch}' not found: {ref_resp.text[:200]}"
            )

        sha = ref_resp.json().get("object", {}).get("sha", "dry-run-sha")

        create_path = f"/repos/{owner}/{repo}/git/refs"
        create_data = {"ref": f"refs/heads/{branch_name}", "sha": sha}
        resp = await self._request("POST", create_path, create_data)
        if resp.status_code not in (200, 201) and not self._dry_run:
            raise GitHubAdapterError(f"Branch creation failed: {resp.text[:200]}")

        logger.info("github_branch_created", owner=owner, repo=repo, branch=branch_name)
        return branch_name

    async def commit_changes(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        message: str,
        files: dict[str, str],
    ) -> str:
        if self._dry_run:
            logger.info("github_dry_commit", files=list(files.keys())[:5])
            return "dry-run-commit-sha"

        blobs: list[dict[str, Any]] = []
        for filepath, content in files.items():
            blob_resp = await self._request(
                "POST",
                f"/repos/{owner}/{repo}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            if blob_resp.status_code != 201:
                raise GitHubAdapterError(f"Blob creation failed for {filepath}")
            blobs.append(
                {"path": filepath, "sha": blob_resp.json()["sha"], "mode": "100644", "type": "blob"}
            )

        branch_ref = f"heads/{branch_name}"
        ref_resp = await self._request("GET", f"/repos/{owner}/{repo}/git/ref/{branch_ref}")

        base_tree_sha: str
        if ref_resp.status_code == 200:
            commit_data = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/git/commits/{ref_resp.json()['object']['sha']}",
            )
            base_tree_sha = commit_data.json()["tree"]["sha"]
        else:
            base_tree_sha = (
                await self._request(
                    "GET",
                    f"/repos/{owner}/{repo}/git/ref/heads/{branch_name}",
                )
            ).json()["object"]["sha"]

        tree_resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/trees",
            {"base_tree": base_tree_sha, "tree": blobs},
        )
        if tree_resp.status_code != 201:
            raise GitHubAdapterError(f"Tree creation failed: {tree_resp.text[:200]}")

        commit_sha = ref_resp.json()["object"]["sha"]
        commit_resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            {
                "message": message,
                "tree": tree_resp.json()["sha"],
                "parents": [commit_sha],
            },
        )
        if commit_resp.status_code != 201:
            raise GitHubAdapterError(f"Commit creation failed: {commit_resp.text[:200]}")

        new_sha = str(commit_resp.json()["sha"])
        await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/ref/{branch_ref}",
            {"sha": new_sha, "force": False},
        )

        logger.info("github_commit", owner=owner, repo=repo, sha=new_sha[:8])
        return new_sha

    async def create_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        data = {
            "title": title,
            "head": branch_name,
            "base": base_branch,
            "body": body,
        }
        resp = await self._request("POST", f"/repos/{owner}/{repo}/pulls", data)
        if resp.status_code not in (200, 201) and not self._dry_run:
            already = await self._find_existing_pr(owner, repo, branch_name)
            if already:
                return already
            raise GitHubAdapterError(f"PR creation failed: {resp.text[:200]}")

        pr_url = str(resp.json().get("html_url", f"dry-run-pr-{branch_name}"))
        logger.info("github_pr_created", url=pr_url)
        return pr_url

    async def _find_existing_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> str | None:
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open",
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return str(data[0].get("html_url", ""))
        return None

    async def add_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment: str,
    ) -> None:
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            {"body": comment},
        )
        if resp.status_code not in (200, 201) and not self._dry_run:
            logger.warning("github_comment_failed", status=resp.status_code)

    async def get_repo_structure(
        self,
        owner: str,
        repo: str,
        path: str = "",
    ) -> list[dict[str, Any]]:
        url_path = (
            f"/repos/{owner}/{repo}/contents/{path}" if path else f"/repos/{owner}/{repo}/contents"
        )
        resp = await self._request("GET", url_path)
        if resp.status_code != 200 and not self._dry_run:
            return []
        data = resp.json()
        if not isinstance(data, list):
            data = [data]
        return [
            {
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "path": item.get("path", ""),
            }
            for item in data
        ]


class DryRunGitHubAdapter(GitHubAdapter):
    def __init__(self) -> None:
        logger.info("github_dry_run_adapter")

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_branch: str,
    ) -> str:
        logger.info("dry_create_branch", branch=branch_name)
        return branch_name

    async def commit_changes(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        message: str,
        files: dict[str, str],
    ) -> str:
        logger.info("dry_commit", files=list(files.keys())[:5])
        return "dry-run-commit"

    async def create_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        logger.info("dry_create_pr", title=title)
        return f"https://github.com/{owner}/{repo}/pull/dry-run"

    async def add_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment: str,
    ) -> None:
        logger.info("dry_pr_comment", pr=pr_number)

    async def get_repo_structure(
        self,
        owner: str,
        repo: str,
        path: str = "",
    ) -> list[dict[str, Any]]:
        return [{"name": "dry-run", "type": "dir", "path": ""}]
