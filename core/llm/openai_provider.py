"""OpenAI provider adapter. See docs/AI_SPEC.md #1, #1.1a.

Translates our provider-agnostic types (core.llm.base) to and from the OpenAI
Chat Completions API. Nothing OpenAI-shaped (a ChatCompletionMessage, a
ChatCompletionMessageToolCall, ...) is allowed to leak past this file.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

from core.llm.base import (
    KeyStatus,
    Message,
    ProviderCapabilities,
    StopReason,
    StructuredResult,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolTurnResult,
)
from core.llm.errors import LLMAuthError, LLMRateLimited, LLMSchemaError, LLMTimeout

_FINISH_REASON_MAP: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _translate_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """A Message with tool_results becomes one role="tool" entry per result —
    OpenAI has no batched "here are all the tool outputs" shape.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.tool_results:
            for result in msg.tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "content": result.content,
                    }
                )
            continue

        entry: dict[str, Any] = {"role": msg.role}
        if msg.text is not None:
            entry["content"] = msg.text
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in msg.tool_calls
            ]
        out.append(entry)
    return out


class OpenAIProvider:
    name = "openai"
    capabilities = ProviderCapabilities(structured_output=True, tool_use=True)

    def __init__(self, api_key: str) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self._openai = openai

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        timeout_s: float = 60.0,
    ) -> StructuredResult:
        started = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",
                        "schema": schema,
                        "strict": True,
                    },
                },
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
            )
        except self._openai.AuthenticationError as exc:
            raise LLMAuthError(str(exc)) from exc
        except self._openai.RateLimitError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except self._openai.APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        content = resp.choices[0].message.content
        if content is None:
            raise LLMSchemaError("OpenAI returned no content for a structured-output request")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMSchemaError(f"OpenAI structured output was not valid JSON: {exc}") from exc

        usage = resp.usage
        return StructuredResult(
            data=data,
            model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
            raw=resp,
        )

    def complete_with_tools(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        timeout_s: float = 90.0,
    ) -> ToolTurnResult:
        started = time.monotonic()
        openai_messages = [
            {"role": "system", "content": system},
            *_translate_openai_messages(messages),
        ]
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=cast(Any, openai_messages),
                tools=cast(Any, openai_tools if openai_tools else self._openai.NOT_GIVEN),
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
            )
        except self._openai.AuthenticationError as exc:
            raise LLMAuthError(str(exc)) from exc
        except self._openai.RateLimitError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except self._openai.APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        choice = resp.choices[0]
        # We only ever declare function-type tools (see openai_tools above), so
        # every returned call is a function call — cast rather than narrow with
        # isinstance, since the "custom tool" variant only exists for a feature
        # (freeform/grammar-constrained tools) this adapter never opts into.
        tool_calls = tuple(
            ToolCall(
                id=tc.id,
                name=cast(Any, tc).function.name,
                arguments=json.loads(cast(Any, tc).function.arguments)
                if cast(Any, tc).function.arguments
                else {},
            )
            for tc in (choice.message.tool_calls or [])
        )
        usage = resp.usage
        return ToolTurnResult(
            text=choice.message.content,
            tool_calls=tool_calls,
            stop_reason=_FINISH_REASON_MAP.get(choice.finish_reason, "end_turn"),
            model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
            raw=resp,
        )

    def validate_key(self) -> KeyStatus:
        try:
            self._client.models.list()
        except self._openai.AuthenticationError as exc:
            return KeyStatus(valid=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return KeyStatus(valid=False, message=str(exc))
        return KeyStatus(valid=True)


# Re-exported for tests that need to construct a ToolResult without importing
# core.llm.base directly.
__all__ = ["OpenAIProvider", "ToolResult"]
