"""Provider-agnostic LLM types. See docs/AI_SPEC.md #1.

Everything here is OUR shape, not any vendor's. Each provider adapter
translates in both directions at its own boundary — nothing provider-shaped
(an OpenAI ChatCompletionMessage, an Anthropic ContentBlock, ...) is allowed
to leak past core/llm/ into core/agent/ or core/engine/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ToolCall:
    """A model's request to invoke one of the tools it was offered."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The outcome of executing a ToolCall, fed back to the model on the next turn.

    tool_name duplicates what the originating ToolCall already carries. OpenAI
    and Anthropic key a tool result by tool_call_id alone, but Gemini's
    function-response protocol is name-keyed, not id-keyed — so the name is
    carried here too rather than forcing the Gemini adapter to reconstruct it
    from history. The agent loop always has both when it builds a ToolResult
    from the ToolCall it just executed, so populating it costs nothing.
    """

    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """One turn of a tool-use conversation.

    A message is exactly one of: plain text, an assistant turn that made tool
    calls, or a batch of tool results answering the calls from the previous
    assistant turn. Mixing text and tool_calls on one assistant Message is
    allowed (some providers emit both in one turn); mixing tool_results with
    either is not, since a tool-result message has no other content.
    """

    role: Role
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()

    def __post_init__(self) -> None:
        if self.tool_results and (self.text is not None or self.tool_calls):
            raise ValueError("a tool-result message cannot also carry text or tool_calls")
        if self.role == "user" and self.tool_calls:
            raise ValueError("only an assistant message may carry tool_calls")


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model. `parameters` is a JSON Schema object,
    same convention as `complete_structured`'s `schema` argument.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    raw: Any = None


StopReason = Literal["end_turn", "tool_use", "max_tokens"]


@dataclass(frozen=True)
class ToolTurnResult:
    """One turn of complete_with_tools — never a whole loop. Looping (deciding
    whether to execute tool_calls and call again) is core.agent's job, which is
    what keeps the caps in docs/AI_SPEC.md #7.3 enforceable in exactly one place.
    """

    text: str | None
    tool_calls: tuple[ToolCall, ...]
    stop_reason: StopReason
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    raw: Any = None


@dataclass(frozen=True)
class KeyStatus:
    valid: bool
    message: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """What registry.py reports per provider, so a user whose key belongs to
    a provider without agent support gets the one-shot authoring path and a
    clear explanation, never a crash — see docs/AI_SPEC.md #1.1a.
    """

    structured_output: bool = True
    tool_use: bool = True


class LLMProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

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
    ) -> StructuredResult: ...

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
    ) -> ToolTurnResult: ...

    def validate_key(self) -> KeyStatus: ...


__all__ = [
    "KeyStatus",
    "LLMProvider",
    "Message",
    "ProviderCapabilities",
    "Role",
    "StopReason",
    "StructuredResult",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "ToolTurnResult",
]
