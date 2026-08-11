from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from orchestrator.logging import get_logger
from schemas.execution import ExecutionMode, TaskSource, TaskSpec

logger = get_logger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1"


class TrelloAdapterError(Exception):
    pass


class TrelloRateLimitError(TrelloAdapterError):
    pass


class TrelloCardData(dict):
    """Lightweight dict alias for raw Trello card payloads."""


class TrelloAdapter(ABC):
    """Abstract Trello adapter — B-001-010.

    Implementations: REST polling adapter, webhook-driven adapter.
    """

    @abstractmethod
    async def fetch_cards(
        self,
        board_id: str,
        list_id: str | None = None,
        label_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_card(self, card_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def move_card(self, card_id: str, list_id: str) -> None: ...

    @abstractmethod
    async def add_comment(self, card_id: str, comment: str) -> None: ...

    @abstractmethod
    async def update_card_fields(self, card_id: str, **fields: Any) -> None: ...

    def card_to_task(
        self,
        card: dict[str, Any],
        repository_path: str,
        base_branch: str = "main",
        mode: ExecutionMode = ExecutionMode.DRY_RUN,
    ) -> TaskSpec:
        """Convert a Trello card payload into a TaskSpec (idempotent)."""
        short_link = card.get("shortLink", "")
        card_id = card.get("id", "")
        execution_id = f"trello-{short_link or card_id[:8]}"

        description = card.get("desc", "") or ""
        acceptance = _extract_acceptance_criteria(description)
        agents = _extract_requested_agents(description)

        return TaskSpec(
            execution_id=execution_id,
            source=TaskSource.TRELLO,
            title=card.get("name", "Untitled card"),
            description=description,
            repository_path=repository_path,
            base_branch=base_branch,
            acceptance_criteria=acceptance,
            requested_agents=agents,
            mode=mode,
            metadata={
                "trello_card_id": card_id,
                "trello_short_link": short_link,
                "trello_url": card.get("url", ""),
                "trello_board_id": card.get("idBoard", ""),
                "trello_list_id": card.get("idList", ""),
            },
        )


def _extract_acceptance_criteria(desc: str) -> list[str]:
    """Parse '## Acceptance Criteria' section from card description."""
    criteria: list[str] = []
    in_section = False
    for line in desc.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("##") and "acceptance" in lowered:
            in_section = True
            continue
        if in_section and lowered.startswith("##"):
            break
        if in_section and stripped.startswith(("- ", "* ", "- [ ]", "- [x]")):
            text = stripped.lstrip("-* ").removeprefix("[ ]").removeprefix("[x]").strip()
            if text:
                criteria.append(text)
    return criteria


def _extract_requested_agents(desc: str) -> list[str]:
    """Parse '## Agents' section from card description."""
    agents: list[str] = []
    in_section = False
    for line in desc.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("##") and "agent" in lowered:
            in_section = True
            continue
        if in_section and lowered.startswith("##"):
            break
        if in_section and stripped.startswith(("- ", "* ")):
            text = stripped.lstrip("-* ").strip()
            if text:
                agents.append(text)
    return agents


class TrelloRESTAdapter(TrelloAdapter):
    """Trello REST adapter with idempotent updates and rate-limit handling."""

    MAX_RETRIES = 3
    BACKOFF_BASE = 2.0

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("TRELLO_API_KEY", "")
        self.token = token or os.getenv("TRELLO_TOKEN", "")
        self._dry_run = dry_run
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=TRELLO_API_BASE,
                params={"key": self.api_key, "token": self.token},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if self._dry_run:
            logger.info("trello_dry_run", method=method, path=path)
            return httpx.Response(200, json={"dry_run": True, "id": "dry-run-id"})

        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self.client.request(method, path, params=params, json=json_data)
                if resp.status_code == 429:
                    wait = self.BACKOFF_BASE**attempt
                    logger.warning("trello_rate_limited", wait_seconds=wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    raise TrelloAdapterError(
                        f"Trello API error {resp.status_code}: {resp.text[:200]}"
                    )
                return resp
            except httpx.HTTPError as exc:
                last_exc = exc
                wait = self.BACKOFF_BASE**attempt
                logger.warning("trello_http_error", error=str(exc), wait=wait)
                await asyncio.sleep(wait)
        raise TrelloRateLimitError(
            f"Trello request failed after {self.MAX_RETRIES} retries: {last_exc}"
        )

    async def fetch_cards(
        self,
        board_id: str,
        list_id: str | None = None,
        label_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if list_id:
            resp = await self._request("GET", f"/lists/{list_id}/cards")
            cards = resp.json() if isinstance(resp.json(), list) else []
        else:
            resp = await self._request("GET", f"/boards/{board_id}/cards")
            cards = resp.json() if isinstance(resp.json(), list) else []

        if label_id:
            cards = [c for c in cards if label_id in c.get("idLabels", [])]
        return cards

    async def get_card(self, card_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/cards/{card_id}")
        data = resp.json()
        return dict(data) if isinstance(data, dict) else {}

    async def move_card(self, card_id: str, list_id: str) -> None:
        await self._request("PUT", f"/cards/{card_id}", json_data={"idList": list_id})

    async def add_comment(self, card_id: str, comment: str) -> None:
        await self._request(
            "POST",
            f"/cards/{card_id}/actions/comments",
            json_data={"text": comment},
        )

    async def update_card_fields(self, card_id: str, **fields: Any) -> None:
        await self._request("PUT", f"/cards/{card_id}", json_data=fields)


class DryRunTrelloAdapter(TrelloAdapter):
    def __init__(self) -> None:
        self.cards: dict[str, dict[str, Any]] = {}
        self.comments: list[tuple[str, str]] = []
        logger.info("trello_dry_run_adapter")

    async def fetch_cards(
        self,
        board_id: str,
        list_id: str | None = None,
        label_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return list(self.cards.values())

    async def get_card(self, card_id: str) -> dict[str, Any]:
        return self.cards.get(card_id, {"id": card_id, "name": "dry-run card"})

    async def move_card(self, card_id: str, list_id: str) -> None:
        if card_id in self.cards:
            self.cards[card_id]["idList"] = list_id

    async def add_comment(self, card_id: str, comment: str) -> None:
        self.comments.append((card_id, comment))

    async def update_card_fields(self, card_id: str, **fields: Any) -> None:
        if card_id in self.cards:
            self.cards[card_id].update(fields)


def verify_trello_webhook_signature(
    payload: bytes, signature: str, secret: str, callback_url: str
) -> bool:
    """Verify Trello webhook signature (base64 HMAC-SHA1 of payload + callbackURL).

    Trello sends the X-Trello-Webhook header as base64, not hex — using
    hexdigest() here would never match a real delivery.
    """
    raw_digest = hmac.new(secret.encode(), payload + callback_url.encode(), hashlib.sha1).digest()
    digest = base64.b64encode(raw_digest).decode()
    return hmac.compare_digest(digest, signature)


class TrelloWebhookHandler:
    """Dispatches Trello webhook events to TaskSpec-producing callbacks."""

    def __init__(
        self,
        adapter: TrelloAdapter,
        run_label_id: str,
        on_card: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._adapter = adapter
        self._run_label_id = run_label_id
        self._on_card = on_card

    async def handle_event(self, payload: dict[str, Any]) -> bool:
        action = payload.get("action", {})
        action_type = action.get("type", "")
        card = action.get("data", {}).get("card", {})

        if action_type not in ("updateCard", "createCard"):
            return False

        card_id = card.get("id", "")
        if not card_id:
            return False

        full_card = await self._adapter.get_card(card_id)
        if self._run_label_id in full_card.get("idLabels", []):
            await self._on_card(full_card)
            return True
        return False


async def poll_trello(
    adapter: TrelloAdapter,
    board_id: str,
    list_id: str | None,
    label_id: str,
    on_card: Callable[[dict[str, Any]], Awaitable[None]],
    interval_seconds: int = 60,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Polling loop — kept as a fallback when webhooks are unavailable."""
    logger.info("trello_poll_start", interval=interval_seconds)
    while stop_event is None or not stop_event.is_set():
        try:
            cards = await adapter.fetch_cards(board_id, list_id, label_id)
            for card in cards:
                await on_card(card)
        except Exception as exc:
            logger.error("trello_poll_error", error=str(exc))
        await asyncio.sleep(interval_seconds)
