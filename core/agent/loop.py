"""The bounded tool-use loop. See docs/AI_SPEC.md #6.2, #6.3.

One call, one turn is core.llm's rule (docs/AI_SPEC.md #1.1a) — looping is
this module's job, which is what keeps the caps in limits.py enforceable in
exactly one place.

The model's "I'm done" signal is a synthetic `submit_draft` tool whose
parameters ARE the target Pydantic schema, rather than a second
complete_structured call after the conversation ends. One call per turn
throughout, and the final draft is schema-validated the same way every other
tool call's arguments are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from core.agent.errors import ToolBlocked
from core.agent.limits import DEFAULT_CAPS, UsageCaps, UsageTracker
from core.agent.tools.registry import TOOL_SPECS, ToolContext, execute_tool
from core.db.errors import NotFound
from core.llm.base import LLMProvider, Message, ToolCall, ToolResult, ToolSpec
from core.llm.errors import LLMToolArgError

_SUBMIT_TOOL_NAME = "submit_draft"
_MAX_CONSECUTIVE_ARG_FAILURES = 2

T = TypeVar("T", bound=BaseModel)


def _submit_tool_spec(target_schema: type[BaseModel]) -> ToolSpec:
    return ToolSpec(
        name=_SUBMIT_TOOL_NAME,
        description=(
            "Submit your finished draft. Call this only when you are satisfied with it "
            "— it ends this conversation turn and shows the draft to the user."
        ),
        parameters=target_schema.model_json_schema(),
    )


@dataclass(frozen=True)
class AgentOutcome(Generic[T]):  # noqa: UP046 - py3.11 dev env compat
    draft: T | None
    is_complete: bool
    transcript: tuple[Message, ...]
    usage: UsageTracker
    note: str | None = None


@dataclass
class _ToolFailureCounts:
    """Consecutive-failure count per tool name — per docs/AI_SPEC.md #7.3, two
    consecutive failures on the SAME tool end the loop, not two failures
    anywhere. Malformed arguments (LLMToolArgError) count; a legitimate
    refusal (ToolBlocked, NotFound) does not — the model asked correctly and
    got a real answer, that isn't the model malfunctioning.
    """

    counts: dict[str, int] = field(default_factory=dict)

    def record_failure(self, tool_name: str) -> int:
        self.counts[tool_name] = self.counts.get(tool_name, 0) + 1
        return self.counts[tool_name]

    def record_success(self, tool_name: str) -> None:
        self.counts[tool_name] = 0


def run_agent_loop(
    *,
    provider: LLMProvider,
    model: str,
    system: str,
    messages: list[Message],
    tool_context: ToolContext,
    target_schema: type[T],
    caps: UsageCaps = DEFAULT_CAPS,
) -> AgentOutcome[T]:
    """Drive one or more turns until the model calls submit_draft with a valid
    draft, the caps are exhausted, or the model stops without submitting.

    Cap exhaustion and "model stopped without submitting" are both normal,
    non-exceptional outcomes — is_complete=False, never a raised error. See
    docs/AI_SPEC.md #6.3: an agent that stops early with a usable partial
    state is working correctly.
    """
    tracker = UsageTracker(caps=caps)
    conversation = list(messages)
    tools = [*TOOL_SPECS, _submit_tool_spec(target_schema)]
    failures = _ToolFailureCounts()

    while True:
        if tracker.is_exhausted:
            return AgentOutcome(
                draft=None,
                is_complete=False,
                transcript=tuple(conversation),
                usage=tracker,
                note="Ran out of tool-call or token budget before a draft was submitted.",
            )

        result = provider.complete_with_tools(
            system=system,
            messages=conversation,
            tools=tools,
            model=model,
            timeout_s=caps.max_turn_seconds,
        )
        tracker.record_tokens(result.input_tokens + result.output_tokens)
        conversation.append(
            Message(role="assistant", text=result.text, tool_calls=result.tool_calls)
        )

        if not result.tool_calls:
            return AgentOutcome(
                draft=None,
                is_complete=False,
                transcript=tuple(conversation),
                usage=tracker,
                note=result.text,
            )

        submitted: T | None = None
        tool_results: list[ToolResult] = []

        for call in result.tool_calls:
            if submitted is not None:
                # A submission already validated earlier in this same batch —
                # answer the remaining calls without executing them, so every
                # call in the batch still has a matching result and the
                # transcript stays valid if the caller continues it later.
                tool_results.append(
                    ToolResult(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content="skipped: the draft was already submitted in this turn",
                    )
                )
                continue

            tracker.record_tool_call()

            if call.name == _SUBMIT_TOOL_NAME:
                submitted, outcome_result = _try_submit(call, target_schema)
                tool_results.append(outcome_result)
                if submitted is None:
                    consecutive = failures.record_failure(call.name)
                    if consecutive >= _MAX_CONSECUTIVE_ARG_FAILURES:
                        conversation.append(Message(role="user", tool_results=tuple(tool_results)))
                        return AgentOutcome(
                            draft=None,
                            is_complete=False,
                            transcript=tuple(conversation),
                            usage=tracker,
                            note="The model repeatedly submitted an invalid draft.",
                        )
                else:
                    failures.record_success(call.name)
                continue

            if tracker.tool_calls_remaining <= 0:
                tool_results.append(
                    ToolResult(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content="tool-call budget exhausted for this draft",
                        is_error=True,
                    )
                )
                continue

            result_content, is_error, arg_error = _execute_one(call, tool_context)
            tool_results.append(
                ToolResult(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content=result_content,
                    is_error=is_error,
                )
            )
            if arg_error:
                consecutive = failures.record_failure(call.name)
                if consecutive >= _MAX_CONSECUTIVE_ARG_FAILURES:
                    conversation.append(Message(role="user", tool_results=tuple(tool_results)))
                    return AgentOutcome(
                        draft=None,
                        is_complete=False,
                        transcript=tuple(conversation),
                        usage=tracker,
                        note=f"The model repeatedly called {call.name!r} with invalid arguments.",
                    )
            else:
                failures.record_success(call.name)

        conversation.append(Message(role="user", tool_results=tuple(tool_results)))

        if submitted is not None:
            return AgentOutcome(
                draft=submitted,
                is_complete=True,
                transcript=tuple(conversation),
                usage=tracker,
                note=result.text,
            )


def _try_submit(call: ToolCall, target_schema: type[T]) -> tuple[T | None, ToolResult]:
    try:
        draft = target_schema.model_validate(call.arguments)
    except ValidationError as exc:
        return None, ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            content=f"validation failed, revise and call {_SUBMIT_TOOL_NAME} again: {exc}",
            is_error=True,
        )
    return draft, ToolResult(
        tool_call_id=call.id, tool_name=call.name, content="draft accepted", is_error=False
    )


def _execute_one(call: ToolCall, context: ToolContext) -> tuple[str, bool, bool]:
    """Returns (content, is_error, was_argument_error). was_argument_error is
    tracked separately from is_error because only malformed arguments count
    toward the consecutive-failure cap — a correctly-formed call that got a
    legitimate refusal is not the model malfunctioning.
    """
    try:
        content = execute_tool(call.name, call.arguments, context)
    except LLMToolArgError as exc:
        return f"error: {exc}", True, True
    except ToolBlocked as exc:
        return f"blocked: {exc}", True, False
    except NotFound as exc:
        return f"not found: {exc}", True, False
    return content, False, False
