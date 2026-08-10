"""B-001-036 — GitHub `repository_dispatch` wrapper.

Alternative execution path to running the LangGraph pipeline in-process:
fires a `repository_dispatch` event so `.github/workflows/agentic-run.yml`
runs the same graph in CI instead of locally (E23 in the spec's edge-case
catalog covers dispatch failure handling).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from orchestrator.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.github.com"
MAX_RETRIES = 3
BACKOFF_BASE_SEC = 0.01


class GitHubDispatchError(Exception):
    pass


async def dispatch_github_action(
    owner: str,
    repo: str,
    event_type: str,
    client_payload: dict[str, Any],
    token: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """POST /repos/{owner}/{repo}/dispatches (repository_dispatch).

    Retries on 429 with exponential backoff (matches the pattern already
    used for Trello's rate limiting, E10). Raises `GitHubDispatchError` on
    any non-204 response or exhausted retries — a failed dispatch must
    surface, never be swallowed (E23).
    """
    headers = {
        "Authorization": f"Bearer {token or os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {"event_type": event_type, "client_payload": client_payload}
    path = f"/repos/{owner}/{repo}/dispatches"

    last_error = ""
    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=30.0, transport=transport
    ) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(path, json=body)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                logger.warning("github_dispatch_http_error", error=last_error)
                await asyncio.sleep(BACKOFF_BASE_SEC * (2**attempt))
                continue

            if resp.status_code == 429:
                logger.warning("github_dispatch_rate_limited", attempt=attempt)
                await asyncio.sleep(BACKOFF_BASE_SEC * (2**attempt))
                continue

            if resp.status_code == 204:
                logger.info("github_dispatch_sent", owner=owner, repo=repo, event_type=event_type)
                return

            raise GitHubDispatchError(
                f"repository_dispatch failed ({resp.status_code}): {resp.text[:200]}"
            )

    raise GitHubDispatchError(
        f"repository_dispatch failed after {MAX_RETRIES} retries"
        + (f": {last_error}" if last_error else " (rate limited)")
    )
