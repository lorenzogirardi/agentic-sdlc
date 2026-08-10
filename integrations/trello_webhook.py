"""B-001-010 — Trello webhook receiver.

Standalone FastAPI app that receives Trello webhook callbacks and converts
labelled cards into TaskSpecs for the orchestrator.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response

from integrations.trello_adapter import (
    TrelloRESTAdapter,
    TrelloWebhookHandler,
    verify_trello_webhook_signature,
)
from orchestrator.github_dispatch import dispatch_github_action
from orchestrator.logging import get_logger, setup_logging
from schemas.execution import ExecutionMode, TaskSpec

logger = get_logger(__name__)

RunLocal = Callable[[TaskSpec], Awaitable[dict[str, Any]]]
Dispatch = Callable[[str, str, str, dict[str, Any]], Awaitable[None]]


async def _default_run_local(task: TaskSpec) -> dict[str, Any]:
    """Run the LangGraph-driven pipeline in-process (local/Docker mode)."""
    from orchestrator.engine import Orchestrator
    from orchestrator.execution_context import ExecutionStore
    from orchestrator.policy_engine import PolicyEngine
    from runners.tool_runner import ToolRunner

    policy = PolicyEngine.from_yaml(os.getenv("POLICY_PATH", "policies/default.yaml"))
    orchestrator = Orchestrator(
        store=ExecutionStore(),
        policy_engine=policy,
        runner=ToolRunner(allowed_commands=policy.get_allowed_commands()),
    )
    return await orchestrator.run(task)


def create_webhook_app(
    adapter: TrelloRESTAdapter | None = None,
    webhook_secret: str | None = None,
    callback_url: str | None = None,
    run_label_id: str | None = None,
    execution_mode: str | None = None,
    run_local: RunLocal | None = None,
    dispatch: Dispatch | None = None,
    repository_path: str | None = None,
    base_branch: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
) -> FastAPI:
    setup_logging()
    app = FastAPI(title="Agentic SDLC — Trello Webhook")

    secret = webhook_secret or os.getenv("TRELLO_WEBHOOK_SECRET", "")
    cb_url = callback_url or os.getenv("TRELLO_WEBHOOK_CALLBACK_URL", "")
    label = run_label_id or os.getenv("TRELLO_RUN_LABEL_ID", "")
    trello_adapter = adapter or TrelloRESTAdapter()

    mode = execution_mode or os.getenv("EXECUTION_MODE", "local")
    repo_path: str = (
        repository_path if repository_path is not None else os.getenv("TARGET_REPO_PATH", ".")
    )
    base: str = base_branch if base_branch is not None else os.getenv("TARGET_BASE_BRANCH", "main")
    owner: str = github_owner if github_owner is not None else os.getenv("GITHUB_OWNER", "")
    repo: str = github_repo if github_repo is not None else os.getenv("GITHUB_REPOSITORY", "")
    local_runner = run_local or _default_run_local
    dispatcher = dispatch or dispatch_github_action

    async def on_card(card: dict[str, Any]) -> None:
        logger.info(
            "trello_card_triggered",
            card_id=card.get("id"),
            name=card.get("name"),
            execution_mode=mode,
        )
        task = trello_adapter.card_to_task(
            card,
            repository_path=repo_path,
            base_branch=base,
            mode=ExecutionMode.PR if mode == "github_action" else ExecutionMode.DRY_RUN,
        )

        if mode == "github_action":
            await dispatcher(owner, repo, "trello-card", task.model_dump(mode="json"))
        else:
            await local_runner(task)

    handler = TrelloWebhookHandler(trello_adapter, label or "", on_card)

    @app.head("/webhook/trello")
    async def trello_head() -> Response:
        return Response(status_code=200)

    @app.post("/webhook/trello")
    async def trello_webhook(request: Request) -> Response:
        body = await request.body()
        signature = request.headers.get("x-trello-webhook", "")

        if (
            secret
            and cb_url
            and not verify_trello_webhook_signature(body, signature, secret, cb_url)
        ):
            logger.warning("trello_webhook_bad_signature")
            return Response(status_code=401)

        payload: dict[str, Any] = await request.json()
        handled = await handler.handle_event(payload)
        return Response(status_code=200 if handled else 204)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_webhook_app()
