"""Unit tests for core.agent.limits. See docs/AI_SPEC.md #7.3."""

from __future__ import annotations

import pytest

from core.agent.errors import LimitExceeded
from core.agent.limits import UsageCaps, UsageTracker, check_grounding_budget


def test_tracker_not_exhausted_initially() -> None:
    tracker = UsageTracker()
    assert not tracker.is_exhausted
    assert tracker.tool_calls_remaining == tracker.caps.max_tool_calls
    assert tracker.tokens_remaining == tracker.caps.max_total_tokens


def test_tracker_exhausted_after_max_tool_calls() -> None:
    caps = UsageCaps(max_tool_calls=2)
    tracker = UsageTracker(caps=caps)
    tracker.record_tool_call()
    assert not tracker.is_exhausted
    tracker.record_tool_call()
    assert tracker.is_exhausted
    assert tracker.tool_calls_remaining == 0


def test_tracker_exhausted_after_token_budget() -> None:
    caps = UsageCaps(max_total_tokens=100)
    tracker = UsageTracker(caps=caps)
    tracker.record_tokens(99)
    assert not tracker.is_exhausted
    tracker.record_tokens(1)
    assert tracker.is_exhausted


def test_remaining_never_goes_negative() -> None:
    caps = UsageCaps(max_tool_calls=1, max_total_tokens=10)
    tracker = UsageTracker(caps=caps)
    tracker.record_tool_call()
    tracker.record_tool_call()
    tracker.record_tokens(1000)
    assert tracker.tool_calls_remaining == 0
    assert tracker.tokens_remaining == 0


def test_check_grounding_budget_within_cap_does_not_raise() -> None:
    check_grounding_budget(4000, cap=8000)


def test_check_grounding_budget_over_cap_raises() -> None:
    with pytest.raises(LimitExceeded, match="grounding budget"):
        check_grounding_budget(9000, cap=8000)


def test_check_grounding_budget_exactly_at_cap_does_not_raise() -> None:
    check_grounding_budget(8000, cap=8000)
