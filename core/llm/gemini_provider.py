"""Gemini provider adapter. See docs/AI_SPEC.md #1, #1.1a.

Two divergences from the other two adapters, both because Gemini's protocol
genuinely differs rather than because this adapter chose to:

1. Roles are "user"/"model", not "user"/"assistant" — translated at the
   boundary, never leaking "model" into core.agent.
2. Tool results are matched by function *name*, not by call id (id support
   for parallel calls is newer and inconsistent across SDK versions) — this
   is why core.llm.base.ToolResult carries tool_name alongside tool_call_id.

response_schema is given the same plain JSON Schema dict every other adapter
uses. Gemini's accepted schema shape is a documented OpenAPI 3.0 subset that
doesn't necessarily support every JSON Schema construct (`$defs`/`$ref` in
particular) — this is flagged as unverified against a live endpoint in
PHASE_TRACKER.md; no key was available to exercise it for real.
"""

from __future__ import annotations

import json
import time
from typing import Any

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

_AUTH_STATUS_CODE = 401
_RATE_LIMIT_STATUS_CODE = 429


def _translate_gemini_contents(messages: list[Message]) -> list[Any]:
    from google.genai import types

    out: list[Any] = []
    for msg in messages:
        if msg.tool_results:
            out.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=r.tool_call_id,
                                name=r.tool_name,
                                response={"content": r.content, "is_error": r.is_error},
                            )
                        )
                        for r in msg.tool_results
                    ],
                )
            )
            continue

        parts: list[Any] = []
        if msg.text is not None:
            parts.append(types.Part(text=msg.text))
        for call in msg.tool_calls:
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=call.id, name=call.name, args=call.arguments
                    )
                )
            )
        out.append(types.Content(role="model" if msg.role == "assistant" else "user", parts=parts))
    return out


class GeminiProvider:
    name = "gemini"
    capabilities = ProviderCapabilities(structured_output=True, tool_use=True)

    def __init__(self, api_key: str) -> None:
        from google import genai
        from google.genai import errors

        self._client = genai.Client(api_key=api_key)
        self._errors = errors

    def _status_code(self, exc: Exception) -> int | None:
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) else None

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
        from google.genai import types

        started = time.monotonic()
        try:
            resp = self._client.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=[types.Part(text=user)])],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
                ),
            )
        except self._errors.ClientError as exc:
            status = self._status_code(exc)
            if status == _AUTH_STATUS_CODE:
                raise LLMAuthError(str(exc)) from exc
            if status == _RATE_LIMIT_STATUS_CODE:
                raise LLMRateLimited(str(exc)) from exc
            raise
        except self._errors.ServerError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except TimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        text = resp.text
        if not text:
            raise LLMSchemaError("Gemini returned no text for a structured-output request")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMSchemaError(f"Gemini structured output was not valid JSON: {exc}") from exc

        usage = resp.usage_metadata
        return StructuredResult(
            data=data,
            model=resp.model_version or model,
            input_tokens=usage.prompt_token_count if usage and usage.prompt_token_count else 0,
            output_tokens=usage.candidates_token_count
            if usage and usage.candidates_token_count
            else 0,
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
        from google.genai import types

        started = time.monotonic()
        function_declarations = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters=t.parameters
            )
            for t in tools
        ]
        try:
            resp = self._client.models.generate_content(
                model=model,
                contents=_translate_gemini_contents(messages),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[types.Tool(function_declarations=function_declarations)]
                    if function_declarations
                    else None,
                    # Explicit: we pass tool schemas, not Python callables, so the
                    # SDK would not auto-execute them anyway — set for clarity and
                    # to guard against a future SDK version changing that default.
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
                ),
            )
        except self._errors.ClientError as exc:
            status = self._status_code(exc)
            if status == _AUTH_STATUS_CODE:
                raise LLMAuthError(str(exc)) from exc
            if status == _RATE_LIMIT_STATUS_CODE:
                raise LLMRateLimited(str(exc)) from exc
            raise
        except self._errors.ServerError as exc:
            raise LLMRateLimited(str(exc)) from exc
        except TimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc

        latency_ms = (time.monotonic() - started) * 1000
        candidate = resp.candidates[0] if resp.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        text_parts = [p.text for p in parts if p.text]
        tool_calls = tuple(
            ToolCall(
                id=p.function_call.id or p.function_call.name,
                name=p.function_call.name,
                arguments=dict(p.function_call.args or {}),
            )
            for p in parts
            if p.function_call
        )
        finish_reason = (
            str(candidate.finish_reason) if candidate and candidate.finish_reason else ""
        )
        stop_reason: StopReason = (
            "tool_use"
            if tool_calls
            else ("max_tokens" if "MAX_TOKENS" in finish_reason else "end_turn")
        )
        usage = resp.usage_metadata
        return ToolTurnResult(
            text="".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            model=resp.model_version or model,
            input_tokens=usage.prompt_token_count if usage and usage.prompt_token_count else 0,
            output_tokens=usage.candidates_token_count
            if usage and usage.candidates_token_count
            else 0,
            latency_ms=latency_ms,
            raw=resp,
        )

    def validate_key(self) -> KeyStatus:
        try:
            list(self._client.models.list())
        except self._errors.ClientError as exc:
            return KeyStatus(valid=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return KeyStatus(valid=False, message=str(exc))
        return KeyStatus(valid=True)
