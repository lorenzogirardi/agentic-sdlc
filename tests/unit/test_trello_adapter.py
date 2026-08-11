"""B-001-010 — Trello Adapter tests."""

import base64
import hashlib
import hmac

import pytest

from integrations.trello_adapter import (
    DryRunTrelloAdapter,
    TrelloWebhookHandler,
    _extract_acceptance_criteria,
    _extract_requested_agents,
    verify_trello_webhook_signature,
)
from schemas.execution import ExecutionMode, TaskSource


class TestCardToTask:
    def setup_method(self) -> None:
        self.adapter = DryRunTrelloAdapter()

    def test_minimal_card(self) -> None:
        card = {
            "id": "abc123",
            "shortLink": "xY1z",
            "name": "Add endpoint",
            "desc": "",
            "idBoard": "board1",
            "idList": "list1",
            "url": "https://trello.com/c/xY1z",
        }
        task = self.adapter.card_to_task(card, "./repo")
        assert task.title == "Add endpoint"
        assert task.source == TaskSource.TRELLO
        assert task.execution_id == "trello-xY1z"
        assert task.metadata["trello_card_id"] == "abc123"
        assert task.mode == ExecutionMode.DRY_RUN

    def test_card_with_acceptance_criteria(self) -> None:
        card = {
            "id": "c1",
            "shortLink": "s1",
            "name": "Feature",
            "desc": (
                "Some description\n\n"
                "## Acceptance Criteria\n"
                "- endpoint returns 200\n"
                "- tests pass\n"
                "- [ ] docs updated\n\n"
                "## Other Section\n"
                "- not a criterion\n"
            ),
        }
        task = self.adapter.card_to_task(card, "./repo")
        assert task.acceptance_criteria == [
            "endpoint returns 200",
            "tests pass",
            "docs updated",
        ]

    def test_card_with_agents_section(self) -> None:
        card = {
            "id": "c2",
            "shortLink": "s2",
            "name": "Feature",
            "desc": "## Agents\n- security\n- test_pyramid\n\n## Notes\n- foo\n",
        }
        task = self.adapter.card_to_task(card, "./repo")
        assert task.requested_agents == ["security", "test_pyramid"]

    def test_execution_id_fallback_to_card_id(self) -> None:
        card = {"id": "abcdef1234567890", "name": "X", "desc": ""}
        task = self.adapter.card_to_task(card, "./repo")
        assert task.execution_id == "trello-abcdef12"

    def test_idempotent_conversion(self) -> None:
        card = {"id": "c3", "shortLink": "s3", "name": "T", "desc": ""}
        t1 = self.adapter.card_to_task(card, "./repo")
        t2 = self.adapter.card_to_task(card, "./repo")
        assert t1.execution_id == t2.execution_id


class TestDescriptionParsing:
    def test_no_sections(self) -> None:
        assert _extract_acceptance_criteria("plain description") == []
        assert _extract_requested_agents("plain description") == []

    def test_empty_description(self) -> None:
        assert _extract_acceptance_criteria("") == []
        assert _extract_requested_agents("") == []

    def test_star_bullets(self) -> None:
        desc = "## Acceptance Criteria\n* first\n* second\n"
        assert _extract_acceptance_criteria(desc) == ["first", "second"]


class TestWebhookSignature:
    def test_valid_signature(self) -> None:
        secret = "my-secret"
        callback = "https://example.com/webhook"
        payload = b'{"action": {}}'
        sig = base64.b64encode(
            hmac.new(secret.encode(), payload + callback.encode(), hashlib.sha1).digest()
        ).decode()
        assert verify_trello_webhook_signature(payload, sig, secret, callback)

    def test_hex_signature_is_rejected(self) -> None:
        """Regression: Trello signs with base64, not hex — hex must never validate."""
        secret = "my-secret"
        callback = "https://example.com/webhook"
        payload = b'{"action": {}}'
        hex_sig = hmac.new(secret.encode(), payload + callback.encode(), hashlib.sha1).hexdigest()
        assert not verify_trello_webhook_signature(payload, hex_sig, secret, callback)

    def test_invalid_signature(self) -> None:
        assert not verify_trello_webhook_signature(
            b"payload", "deadbeef", "secret", "https://example.com"
        )


class TestDryRunAdapter:
    async def test_idempotent_comment(self) -> None:
        adapter = DryRunTrelloAdapter()
        await adapter.add_comment("card1", "execution started")
        await adapter.add_comment("card1", "execution started")
        assert adapter.comments == [
            ("card1", "execution started"),
            ("card1", "execution started"),
        ]

    async def test_move_card(self) -> None:
        adapter = DryRunTrelloAdapter()
        adapter.cards["c1"] = {"id": "c1", "idList": "todo"}
        await adapter.move_card("c1", "in-progress")
        assert adapter.cards["c1"]["idList"] == "in-progress"

    async def test_update_fields_idempotent(self) -> None:
        adapter = DryRunTrelloAdapter()
        adapter.cards["c1"] = {"id": "c1", "name": "old"}
        await adapter.update_card_fields("c1", name="new")
        await adapter.update_card_fields("c1", name="new")
        assert adapter.cards["c1"]["name"] == "new"


class TestWebhookHandler:
    async def test_labelled_card_triggers_callback(self) -> None:
        adapter = DryRunTrelloAdapter()
        adapter.cards["c1"] = {
            "id": "c1",
            "name": "Task",
            "idLabels": ["label-run"],
        }
        received: list[dict] = []

        async def on_card(card: dict) -> None:
            received.append(card)

        handler = TrelloWebhookHandler(adapter, "label-run", on_card)
        handled = await handler.handle_event(
            {"action": {"type": "updateCard", "data": {"card": {"id": "c1"}}}}
        )
        assert handled is True
        assert len(received) == 1

    async def test_unlabelled_card_ignored(self) -> None:
        adapter = DryRunTrelloAdapter()
        adapter.cards["c1"] = {"id": "c1", "idLabels": []}
        received: list[dict] = []

        async def on_card(card: dict) -> None:
            received.append(card)

        handler = TrelloWebhookHandler(adapter, "label-run", on_card)
        handled = await handler.handle_event(
            {"action": {"type": "updateCard", "data": {"card": {"id": "c1"}}}}
        )
        assert handled is False
        assert received == []

    async def test_non_card_event_ignored(self) -> None:
        adapter = DryRunTrelloAdapter()

        async def on_card(card: dict) -> None:
            pytest.fail("should not be called")

        handler = TrelloWebhookHandler(adapter, "label-run", on_card)
        handled = await handler.handle_event({"action": {"type": "createList", "data": {}}})
        assert handled is False
