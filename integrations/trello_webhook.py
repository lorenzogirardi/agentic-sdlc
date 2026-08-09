"""B-001-010 — Trello webhook receiver.

Standalone FastAPI app that receives Trello webhook callbacks and converts
labelled cards into TaskSpecs for the orchestrator.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request, Response

from integrations.trello_adapter import (
    TrelloRESTAdapter,
    TrelloWebhookHandler,
    verify_trello_webhook_signature,
)
from orchestrator.logging import get_logger, setup_logging

logger = get_logger(__name__)


def create_webhook_app(
    adapter: TrelloRESTAdapter | None = None,
    webhook_secret: str | None = None,
    callback_url: str | None = None,
    run_label_id: str | None = None,
) -> FastAPI:
    setup_logging()
    app = FastAPI(title="Agentic SDLC — Trello Webhook")

    secret = webhook_secret or os.getenv("TRELLO_WEBHOOK_SECRET", "")
    cb_url = callback_url or os.getenv("TRELLO_WEBHOOK_CALLBACK_URL", "")
    label = run_label_id or os.getenv("TRELLO_RUN_LABEL_ID", "")
    trello_adapter = adapter or TrelloRESTAdapter()

    async def on_card(card: dict[str, Any]) -> None:
        logger.info(
            "trello_card_triggered",
            card_id=card.get("id"),
            name=card.get("name"),
        )

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
