"""Unit tests for core.agent.loop.run_agent_loop, against a scripted fake
provider — no network, no real LLM. See docs/AI_SPEC.md #6.2, #6.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from core.agent.limits import UsageCaps
from core.agent.loop import run_agent_loop
from core.agent.tools.registry import ToolContext
from core.llm.base import Message, ProviderCapabilities, ToolCall, ToolSpec, ToolTurnResult
from core.models.common import Page
from core.models.knowledge import KnowledgeDoc


class _TargetSchema(BaseModel):
    module: str
    topic: str
    question: str


class _FakeProvider:
    """Returns scripted ToolTurnResults in order. Asserts it is never called
    more times than scripted — a caller ignoring caps would fail this loudly
    rather than silently looping forever.
    """

    name = "fake"
    capabilities = ProviderCapabilities()

    def __init__(self, responses: list[ToolTurnResult]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete_structured(self, **_kwargs: object) -> object:
        raise NotImplementedError("the loop must never call complete_structured")

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
        if self.calls >= len(self._responses):
            raise AssertionError("complete_with_tools called more times than scripted")
        response = self._responses[self.calls]
        self.calls += 1
        return response

    def validate_key(self) -> object:
        raise NotImplementedError


def _turn(
    *, text: str | None = None, tool_calls: tuple[ToolCall, ...] = (), stop_reason: str = "tool_use"
) -> ToolTurnResult:
    return ToolTurnResult(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,  # type: ignore[arg-type]
        model="fake-model",
        input_tokens=10,
        output_tokens=10,
        latency_ms=1.0,
    )


def _submit_call(**kwargs: object) -> ToolCall:
    return ToolCall(id=str(uuid4()), name="submit_draft", arguments=kwargs)


def _make_doc() -> KnowledgeDoc:
    return KnowledgeDoc(
        id=uuid4(),
        slug="doc",
        tier="verified",  # type: ignore[arg-type]
        status="published",  # type: ignore[arg-type]
        title="Doc",
        summary="Summary",
        body_md="Body",
        verification_level="ai_generated",  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _FakeKnowledgeRepo:
    def search(
        self, query: str | None = None, *, filters: object, limit: int = 25
    ) -> Page[KnowledgeDoc]:
        return Page[KnowledgeDoc](items=(_make_doc(),), total=1, offset=0, limit=limit)

    def get_by_slug(self, slug: str) -> KnowledgeDoc | None:
        return _make_doc() if slug == "doc" else None


def _context() -> ToolContext:
    return ToolContext(knowledge_repo=_FakeKnowledgeRepo(), uploads={})  # type: ignore[arg-type]


def test_immediate_valid_submission_completes() -> None:
    call = _submit_call(module="Inflation", topic="Inflation Dynamics", question="Why?")
    provider = _FakeProvider([_turn(tool_calls=(call,))])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system prompt",
        messages=[Message(role="user", text="draft a question")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is True
    assert outcome.draft == _TargetSchema(
        module="Inflation", topic="Inflation Dynamics", question="Why?"
    )
    assert provider.calls == 1


def test_invalid_submission_then_valid_retry_completes() -> None:
    bad_call = _submit_call(module="Inflation")  # missing required fields
    good_call = _submit_call(module="Inflation", topic="Inflation Dynamics", question="Why?")
    provider = _FakeProvider([_turn(tool_calls=(bad_call,)), _turn(tool_calls=(good_call,))])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is True
    assert provider.calls == 2


def test_two_consecutive_invalid_submissions_ends_the_loop() -> None:
    bad_call = _submit_call(module="Inflation")
    provider = _FakeProvider([_turn(tool_calls=(bad_call,)), _turn(tool_calls=(bad_call,))])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is False
    assert outcome.draft is None
    assert outcome.note is not None and "repeatedly submitted" in outcome.note
    assert provider.calls == 2


def test_successful_tool_call_then_submission() -> None:
    search_call = ToolCall(id="1", name="search_knowledge", arguments={"query": "doc"})
    submit_call = _submit_call(module="Inflation", topic="Inflation Dynamics", question="Why?")
    provider = _FakeProvider([_turn(tool_calls=(search_call,)), _turn(tool_calls=(submit_call,))])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is True
    # transcript carries the tool call, its result, and the submission exchange
    assert any(m.tool_results for m in outcome.transcript)


def test_model_stops_without_submitting_returns_incomplete() -> None:
    provider = _FakeProvider([_turn(text="I need more information from you.", tool_calls=())])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is False
    assert outcome.draft is None
    assert outcome.note == "I need more information from you."
    assert provider.calls == 1


def test_tool_call_budget_exhaustion_stops_before_a_second_provider_call() -> None:
    search_call = ToolCall(id="1", name="search_knowledge", arguments={"query": "doc"})
    provider = _FakeProvider([_turn(tool_calls=(search_call,))])
    caps = UsageCaps(max_tool_calls=1)

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
        caps=caps,
    )

    assert outcome.is_complete is False
    assert outcome.note is not None and "budget" in outcome.note
    assert provider.calls == 1  # never asked the model again after the cap tripped


def test_two_consecutive_malformed_tool_calls_ends_the_loop() -> None:
    # search_knowledge requires a 'query' argument — omitting it twice in a
    # row on the same tool should end the loop per docs/AI_SPEC.md #7.3.
    bad_call = ToolCall(id="1", name="search_knowledge", arguments={})
    provider = _FakeProvider([_turn(tool_calls=(bad_call,)), _turn(tool_calls=(bad_call,))])

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is False
    assert outcome.note is not None and "search_knowledge" in outcome.note
    assert provider.calls == 2


def test_not_found_from_a_tool_does_not_count_as_a_malformed_argument_failure() -> None:
    # A well-formed call that legitimately fails (e.g. slug not found) is not
    # the model malfunctioning — it should NOT trip the 2-strikes cap the way
    # LLMToolArgError does.
    miss_call = ToolCall(id="1", name="read_knowledge", arguments={"slug": "does-not-exist"})
    submit_call = _submit_call(module="Inflation", topic="Inflation Dynamics", question="Why?")
    provider = _FakeProvider(
        [
            _turn(tool_calls=(miss_call,)),
            _turn(tool_calls=(miss_call,)),
            _turn(tool_calls=(submit_call,)),
        ]
    )

    outcome = run_agent_loop(
        provider=provider,  # type: ignore[arg-type]
        model="fake-model",
        system="system",
        messages=[Message(role="user", text="draft")],
        tool_context=_context(),
        target_schema=_TargetSchema,
    )

    assert outcome.is_complete is True
    assert provider.calls == 3
