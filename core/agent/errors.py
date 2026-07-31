"""Typed agent errors. See docs/ARCHITECTURE.md #5.1, #5."""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all typed agent errors."""


class ToolBlocked(AgentError):
    """A tool refused to act — e.g. fetch_url rejected a private/loopback
    address or a disallowed scheme. Fed back to the model as a tool result the
    model can read and route around; never a stack trace to the user
    (docs/ARCHITECTURE.md #5).
    """


class LimitExceeded(AgentError):
    """A turn/token/daily cap was reached. Not an error shown to the user —
    the agent loop catches this and returns the best draft so far, labelled
    incomplete (docs/AI_SPEC.md #6.3, #7.3).
    """
