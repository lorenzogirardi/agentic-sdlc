from __future__ import annotations

import asyncio
import json
import os
import re
import time

from openai import AsyncOpenAI
from pydantic import BaseModel

from orchestrator.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "deepseek-v4-flash-free"
DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0


class OpenCodeError(Exception):
    pass


class OutputValidationError(OpenCodeError):
    pass


class _EmptyCompletionError(Exception):
    """Internal marker: retryable, unlike OutputValidationError."""


class OpenCodeAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url or os.getenv("OPENCODE_BASE_URL") or DEFAULT_BASE_URL
        self.api_key = api_key or os.getenv("OPENCODE_API_KEY", "")
        self.model = model or os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, str]],
        response_schema: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict:
        # Native `response_format: json_schema` isn't reliably supported by every
        # OpenCode-routed model (some reject it outright with a 400). Ask for JSON
        # via the prompt instead, and parse leniently — works everywhere.
        if response_schema is not None:
            schema_instruction = {
                "role": "system",
                "content": (
                    "Respond with ONLY valid JSON matching this schema, no prose, "
                    "no markdown code fences:\n"
                    f"{json.dumps(response_schema.model_json_schema())}"
                ),
            }
            messages = [schema_instruction, *messages]

        model_kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                start = time.perf_counter()
                response = await self.client.chat.completions.create(**model_kwargs)
                duration_ms = (time.perf_counter() - start) * 1000

                content = response.choices[0].message.content or ""
                if not content.strip():
                    # Empty completions from the free-tier model are usually a
                    # transient provider hiccup, not a deterministic bad request —
                    # worth retrying, unlike a genuinely malformed/non-JSON reply.
                    raise _EmptyCompletionError("model returned an empty completion")

                parsed: dict = {}
                if response_schema is not None:
                    parsed = self._validate_output(content, response_schema)
                else:
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        parsed = {"raw_output": content}

                usage = response.usage
                token_usage = {}
                if usage:
                    token_usage = {
                        "prompt_tokens": usage.prompt_tokens or 0,
                        "completion_tokens": usage.completion_tokens or 0,
                        "total_tokens": usage.total_tokens or 0,
                    }

                logger.info(
                    "llm_call",
                    model=self.model,
                    attempt=attempt,
                    duration_ms=duration_ms,
                    tokens=token_usage.get("total_tokens", 0),
                )

                parsed["_meta"] = {
                    "duration_ms": duration_ms,
                    "token_usage": token_usage,
                    "model": self.model,
                }
                return parsed

            except OutputValidationError:
                # Schema/JSON validation errors are deterministic — never retried.
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_retry",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
                continue

        raise OpenCodeError(f"LLM call failed after {MAX_RETRIES + 1} attempts: {last_error}")

    def _validate_output(self, content: str, schema: type[BaseModel]) -> dict:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            stripped = _strip_markdown_fence(content)
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise OutputValidationError(f"Invalid JSON from model: {exc}") from exc

        try:
            validated = schema.model_validate(data)
            return validated.model_dump()
        except Exception as exc:
            raise OutputValidationError(
                f"Output does not match schema {schema.__name__}: {exc}"
            ) from exc


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _strip_markdown_fence(content: str) -> str:
    match = _FENCE_RE.search(content)
    return match.group(1).strip() if match else content
