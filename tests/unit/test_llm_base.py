"""Unit tests for core.llm.base message invariants."""

from __future__ import annotations

import pytest

from core.llm.base import Message, ToolCall, ToolResult


def test_plain_user_message_is_valid() -> None:
    msg = Message(role="user", text="hello")
    assert msg.text == "hello"


def test_assistant_message_may_carry_text_and_tool_calls() -> None:
    call = ToolCall(id="1", name="search_knowledge", arguments={"query": "x"})
    msg = Message(role="assistant", text="let me check", tool_calls=(call,))
    assert msg.tool_calls == (call,)


def test_user_message_cannot_carry_tool_calls() -> None:
    call = ToolCall(id="1", name="search_knowledge", arguments={})
    with pytest.raises(ValueError, match="only an assistant message"):
        Message(role="user", tool_calls=(call,))


def test_tool_result_message_cannot_also_carry_text() -> None:
    result = ToolResult(tool_call_id="1", tool_name="search_knowledge", content="[]")
    with pytest.raises(ValueError, match="tool-result message"):
        Message(role="user", text="hi", tool_results=(result,))


def test_tool_result_message_cannot_also_carry_tool_calls() -> None:
    call = ToolCall(id="1", name="search_knowledge", arguments={})
    result = ToolResult(tool_call_id="1", tool_name="search_knowledge", content="[]")
    with pytest.raises(ValueError, match="tool-result message"):
        Message(role="assistant", tool_calls=(call,), tool_results=(result,))


def test_pure_tool_result_message_is_valid() -> None:
    result = ToolResult(tool_call_id="1", tool_name="search_knowledge", content="[]")
    msg = Message(role="user", tool_results=(result,))
    assert msg.tool_results == (result,)
