"""B-001-036 — github_dispatch.py (repository_dispatch) tests."""

from __future__ import annotations

import httpx
import pytest

from orchestrator.github_dispatch import GitHubDispatchError, dispatch_github_action


def _transport(handler):
    return httpx.MockTransport(handler)


class TestDispatchGithubAction:
    async def test_sends_expected_payload_and_auth(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = request.content
            return httpx.Response(204)

        await dispatch_github_action(
            "acme",
            "repo",
            "trello-card",
            {"execution_id": "exec-1"},
            token="tkn",
            transport=_transport(handler),
        )

        assert captured["url"] == "https://api.github.com/repos/acme/repo/dispatches"
        assert captured["auth"] == "Bearer tkn"
        import json

        body = json.loads(captured["body"])
        assert body == {
            "event_type": "trello-card",
            "client_payload": {"execution_id": "exec-1"},
        }

    async def test_non_204_raises_dispatch_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "bad event_type"})

        with pytest.raises(GitHubDispatchError, match="422"):
            await dispatch_github_action(
                "acme", "repo", "trello-card", {}, token="tkn", transport=_transport(handler)
            )

    async def test_retries_on_429_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(429)
            return httpx.Response(204)

        await dispatch_github_action(
            "acme", "repo", "trello-card", {}, token="tkn", transport=_transport(handler)
        )

        assert calls["n"] == 2

    async def test_exhausted_retries_raise(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(GitHubDispatchError):
            await dispatch_github_action(
                "acme", "repo", "trello-card", {}, token="tkn", transport=_transport(handler)
            )
