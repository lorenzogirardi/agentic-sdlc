"""B-001-008 — OpenCode Adapter tests (mocked — no real HTTP calls)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field

from integrations.opencode_adapter import (
    OpenCodeAdapter,
    OpenCodeError,
    OutputValidationError,
)


class PlannerSchema(BaseModel):
    summary: str
    required_agents: list[str] = Field(default_factory=list)


def make_mock_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 5):
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    response.choices = [choice]
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    response.usage = usage
    return response


class TestOpenCodeAdapterMock:
    async def test_valid_json_output(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://mock", api_key="test-key", model="test-model")
        payload = json.dumps({"summary": "Plan", "required_agents": ["lint"]})
        mock_create = AsyncMock(return_value=make_mock_response(payload))
        adapter._client = MagicMock()
        adapter._client.chat.completions.create = mock_create

        result = await adapter.chat(
            [{"role": "user", "content": "plan"}],
            response_schema=PlannerSchema,
        )
        assert result["summary"] == "Plan"
        assert result["required_agents"] == ["lint"]
        assert result["_meta"]["token_usage"]["total_tokens"] == 15

    async def test_invalid_json_raises_validation_error(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://mock", api_key="test-key", model="test-model")
        mock_create = AsyncMock(return_value=make_mock_response("not json at all"))
        adapter._client = MagicMock()
        adapter._client.chat.completions.create = mock_create

        with pytest.raises(OutputValidationError, match="Invalid JSON"):
            await adapter.chat(
                [{"role": "user", "content": "plan"}],
                response_schema=PlannerSchema,
            )

    async def test_schema_mismatch_rejected(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://mock", api_key="test-key", model="test-model")
        payload = json.dumps({"wrong_field": 123})
        mock_create = AsyncMock(return_value=make_mock_response(payload))
        adapter._client = MagicMock()
        adapter._client.chat.completions.create = mock_create

        with pytest.raises(OutputValidationError, match="does not match schema"):
            await adapter.chat(
                [{"role": "user", "content": "plan"}],
                response_schema=PlannerSchema,
            )

    async def test_retry_on_failure_then_success(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://mock", api_key="test-key", model="test-model")
        payload = json.dumps({"summary": "ok", "required_agents": []})
        mock_create = AsyncMock(side_effect=[Exception("transient"), make_mock_response(payload)])
        adapter._client = MagicMock()
        adapter._client.chat.completions.create = mock_create

        result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert result["summary"] == "ok"
        assert mock_create.call_count == 2

    async def test_exhausted_retries_raise(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://mock", api_key="test-key", model="test-model")
        mock_create = AsyncMock(side_effect=Exception("persistent failure"))
        adapter._client = MagicMock()
        adapter._client.chat.completions.create = mock_create

        with pytest.raises(OpenCodeError, match="failed after"):
            await adapter.chat([{"role": "user", "content": "hi"}])
        assert mock_create.call_count == 3  # MAX_RETRIES + 1

    def test_env_fallbacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCODE_BASE_URL", "http://env-url")
        monkeypatch.setenv("OPENCODE_API_KEY", "env-key")
        monkeypatch.setenv("OPENCODE_MODEL", "env-model")
        adapter = OpenCodeAdapter()
        assert adapter.base_url == "http://env-url"
        assert adapter.api_key == "env-key"
        assert adapter.model == "env-model"

    def test_no_hardcoded_model_in_default_init(self) -> None:
        adapter = OpenCodeAdapter(base_url="http://x", api_key="k")
        assert adapter.model == "deepseek-v4-flash-free"  # default only, overridable
