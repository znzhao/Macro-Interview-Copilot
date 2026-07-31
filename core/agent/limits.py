"""Usage bounds for the authoring agent. See docs/AI_SPEC.md #7.3.

Per-draft and per-turn caps are pure, in-memory, and enforced here. Per-day
caps (50 drafts/user/day, 20 community submissions/user/day) are
deliberately NOT implemented in this pass: docs/AI_SPEC.md #7.3 requires them
to live in the database, since st.session_state is per-browser-session and
trivially reset by opening a new tab — but no table for that counter exists
yet in the Phase 2 schema (migrations 0003-0005). Building one is a follow-up,
not an oversight; wiring a UI-layer cap against session state instead would
be actively worse than not having one, since it would look enforced without
being enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.agent.errors import LimitExceeded


@dataclass(frozen=True)
class UsageCaps:
    max_tool_calls: int = 8
    max_total_tokens: int = 40_000
    max_grounding_tokens: int = 8_000
    max_turn_seconds: float = 90.0


DEFAULT_CAPS = UsageCaps()


@dataclass
class UsageTracker:
    """Mutable per-draft counter. One instance per authoring session — never
    shared across users or across drafts, since a shared instance would leak
    one user's budget into another's (the same class of bug D15 avoids for
    notifications, just in a different table).
    """

    caps: UsageCaps = field(default_factory=lambda: DEFAULT_CAPS)
    tool_calls_used: int = 0
    tokens_used: int = 0

    def record_tool_call(self) -> None:
        self.tool_calls_used += 1

    def record_tokens(self, count: int) -> None:
        self.tokens_used += count

    @property
    def tool_calls_remaining(self) -> int:
        return max(0, self.caps.max_tool_calls - self.tool_calls_used)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.caps.max_total_tokens - self.tokens_used)

    @property
    def is_exhausted(self) -> bool:
        """Cap exhaustion is a normal outcome, not an error — the loop checks
        this before each turn and returns the best draft so far, labelled
        incomplete, rather than raising (docs/AI_SPEC.md #6.3).
        """
        return self.tool_calls_used >= self.caps.max_tool_calls or (
            self.tokens_used >= self.caps.max_total_tokens
        )


def check_grounding_budget(
    total_token_estimate: int, *, cap: int = DEFAULT_CAPS.max_grounding_tokens
) -> None:
    """Raises LimitExceeded if the user's selected knowledge documents alone
    exceed the grounding budget — checked before the first model call, so the
    UI's budget meter (docs/UI_SPEC.md #1.2c) and this check agree on the
    same number rather than the UI silently allowing what the backend refuses.
    """
    if total_token_estimate > cap:
        raise LimitExceeded(
            f"selected knowledge documents use about {total_token_estimate} tokens, "
            f"over the {cap}-token grounding budget — deselect one and try again"
        )
