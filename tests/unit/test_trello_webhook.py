"""B-001-033 — Trello webhook on_card wiring (was previously a no-op)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi.testclient import TestClient

from integrations.trello_adapter import DryRunTrelloAdapter
from integrations.trello_webhook import create_webhook_app
from schemas.execution import TaskSpec

LABEL_ID = "label-run"
CARD_ID = "card-1"


def _adapter_with_card(labelled: bool = True) -> DryRunTrelloAdapter:
    adapter = DryRunTrelloAdapter()
    adapter.cards[CARD_ID] = {
        "id": CARD_ID,
        "name": "Add health endpoint",
        "idLabels": [LABEL_ID] if labelled else [],
        "desc": "## Acceptance Criteria\n- returns 200\n",
        "shortLink": "abc123",
    }
    return adapter


def _payload(action_type: str = "updateCard") -> dict[str, Any]:
    return {"action": {"type": action_type, "data": {"card": {"id": CARD_ID}}}}


class TestLocalMode:
    def test_matching_label_triggers_run_local(self) -> None:
        calls: list[TaskSpec] = []

        async def run_local(task: TaskSpec) -> dict[str, Any]:
            calls.append(task)
            return {"verdict": "PASS"}

        app = create_webhook_app(
            adapter=_adapter_with_card(),
            run_label_id=LABEL_ID,
            execution_mode="local",
            run_local=run_local,
            repository_path="/repo",
        )
        client = TestClient(app)

        resp = client.post("/webhook/trello", json=_payload())

        assert resp.status_code == 200
        assert len(calls) == 1
        assert calls[0].title == "Add health endpoint"
        assert calls[0].repository_path == "/repo"

    def test_unlabelled_card_does_not_trigger(self) -> None:
        calls: list[TaskSpec] = []

        async def run_local(task: TaskSpec) -> dict[str, Any]:
            calls.append(task)
            return {}

        app = create_webhook_app(
            adapter=_adapter_with_card(labelled=False),
            run_label_id=LABEL_ID,
            execution_mode="local",
            run_local=run_local,
        )
        client = TestClient(app)

        resp = client.post("/webhook/trello", json=_payload())

        assert resp.status_code == 204
        assert calls == []


class TestGithubActionMode:
    def test_dispatches_instead_of_running_locally(self) -> None:
        run_local_calls: list[TaskSpec] = []
        dispatch_calls: list[tuple[str, str, str, dict[str, Any]]] = []

        async def run_local(task: TaskSpec) -> dict[str, Any]:
            run_local_calls.append(task)
            return {}

        async def dispatch(owner: str, repo: str, event_type: str, payload: dict[str, Any]) -> None:
            dispatch_calls.append((owner, repo, event_type, payload))

        app = create_webhook_app(
            adapter=_adapter_with_card(),
            run_label_id=LABEL_ID,
            execution_mode="github_action",
            run_local=run_local,
            dispatch=dispatch,
            github_owner="acme",
            github_repo="widgets",
        )
        client = TestClient(app)

        resp = client.post("/webhook/trello", json=_payload())

        assert resp.status_code == 200
        assert run_local_calls == []
        assert len(dispatch_calls) == 1
        owner, repo, event_type, payload = dispatch_calls[0]
        assert (owner, repo, event_type) == ("acme", "widgets", "trello-card")
        assert payload["title"] == "Add health endpoint"


class TestSignatureVerificationUnaffected:
    def test_bad_signature_rejected_before_on_card(self) -> None:
        calls: list[TaskSpec] = []

        async def run_local(task: TaskSpec) -> dict[str, Any]:
            calls.append(task)
            return {}

        app = create_webhook_app(
            adapter=_adapter_with_card(),
            run_label_id=LABEL_ID,
            execution_mode="local",
            run_local=run_local,
            webhook_secret="s3cr3t",
            callback_url="https://example.com/webhook/trello",
        )
        client = TestClient(app)
        body = json.dumps(_payload()).encode()

        resp = client.post(
            "/webhook/trello", content=body, headers={"x-trello-webhook": "bad-signature"}
        )

        assert resp.status_code == 401
        assert calls == []

    def test_good_signature_accepted(self) -> None:
        calls: list[TaskSpec] = []

        async def run_local(task: TaskSpec) -> dict[str, Any]:
            calls.append(task)
            return {}

        secret = "s3cr3t"
        callback = "https://example.com/webhook/trello"
        app = create_webhook_app(
            adapter=_adapter_with_card(),
            run_label_id=LABEL_ID,
            execution_mode="local",
            run_local=run_local,
            webhook_secret=secret,
            callback_url=callback,
        )
        client = TestClient(app)
        body = json.dumps(_payload()).encode()
        digest = hmac.new(secret.encode(), body + callback.encode(), hashlib.sha1).hexdigest()

        resp = client.post("/webhook/trello", content=body, headers={"x-trello-webhook": digest})

        assert resp.status_code == 200
        assert len(calls) == 1
