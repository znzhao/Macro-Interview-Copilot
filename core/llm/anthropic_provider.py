"""Anthropic provider adapter. See docs/AI_SPEC.md #1, #1.1a.

Anthropic has no native "give me JSON matching this schema" response mode, so
complete_structured is implemented as forced tool use: a single synthetic
tool named `_structured_output` whose input_schema is the caller's schema,
with tool_choice pinned to it. The resulting tool_use block's `input` is the
structured data — this is the "Anthropic -> tool-use with an input schema"
approach from docs/AI_SPEC.md #1.1.
"""

from __future__ import annotations

import time
from typing import Any, cast

from core.llm.base import (
    KeyStatus,
    Message,
    ProviderCapabilities,
    StopReason,
    StructuredResult,
    ToolCall,
    ToolSpec,
    ToolTurnResult,
)
from core.llm.errors import LLMAuthError, LLMRateLimited, LLMSchemaError, LLMTimeout

_STRUCTURED_TOOL_NAME = "_structured_output"

_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
}


def _translate_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Anthropic has no "tool" role: tool results travel as a user message
    whose content is a list of tool_result blocks, batched together rather
    than one message per result the way OpenAI wants them.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.tool_results:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.tool_call_id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
                        for r in msg.tool_results
                    ],
                }
            )
            continue

        content: list[dict[str, Any]] = []
        if msg.text is not None:
            content.append({"type": "text", "text": msg.text})
        for call in msg.tool_calls:
            content.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            )
        out.append({"role": msg.role, "content": content})
    return out


class AnthropicProvider:
    name = "anthropic"
    capabilities = ProviderCapabilities(structured_output=True, tool_use=True)

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._anthropic = anthropic

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
            resp = self._client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": _STRUCTURED_TOOL_NAME,
                        "description": "Return the structured result for this request.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": _STRUCTURED_TOOL_NAME},
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
            )
        except self._anthropic.AuthenticationError as exc:
            raise LLMAuthError(str(exc)) from exc
        except self._anthropic.RateLimitError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except self._anthropic.APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        tool_use_block = next((block for block in resp.content if block.type == "tool_use"), None)
        if tool_use_block is None:
            raise LLMSchemaError("Anthropic did not return the forced structured-output tool call")

        return StructuredResult(
            data=dict(tool_use_block.input),
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
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
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        try:
            resp = self._client.messages.create(
                model=model,
                system=system,
                messages=cast(Any, _translate_anthropic_messages(messages)),
                tools=cast(Any, anthropic_tools),
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
            )
        except self._anthropic.AuthenticationError as exc:
            raise LLMAuthError(str(exc)) from exc
        except self._anthropic.RateLimitError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except self._anthropic.APITimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        text_parts = [block.text for block in resp.content if block.type == "text"]
        tool_calls = tuple(
            ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
            for block in resp.content
            if block.type == "tool_use"
        )
        return ToolTurnResult(
            text="".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=_STOP_REASON_MAP.get(resp.stop_reason or "end_turn", "end_turn"),
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_ms=latency_ms,
            raw=resp,
        )

    def validate_key(self) -> KeyStatus:
        try:
            self._client.models.list(limit=1)
        except self._anthropic.AuthenticationError as exc:
            return KeyStatus(valid=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return KeyStatus(valid=False, message=str(exc))
        return KeyStatus(valid=True)
