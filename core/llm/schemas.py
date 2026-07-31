"""Structured-output schemas for the authoring agent. See docs/AI_SPEC.md #2.2,
#6, docs/CONTENT_SPEC.md #6.

Each schema is a Pydantic model. `.model_json_schema()` is what gets passed as
`complete_structured`'s `schema` argument; `.model_validate()` is the
"validate anyway" step (docs/AI_SPEC.md #1.2) applied to the parsed response,
regardless of what the provider claims about its own conformance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.models.answer_key import AnswerKey
from core.models.enums import Difficulty, Frequency, Module, TargetRole


class QuestionDraftSchema(BaseModel):
    """What the authoring agent must return for a question draft.

    Deliberately excludes tier, status, verification_level, author_id, and
    owner_id — those are assigned by the caller (core/agent/authoring.py),
    never by the model. A drafting agent does not get to decide its own
    governance metadata.
    """

    model_config = ConfigDict(extra="forbid")

    module: Module
    topic: str
    question: str = Field(min_length=20, max_length=1200)
    difficulty: Difficulty
    frequency: Frequency | None = None
    target_roles: tuple[TargetRole, ...] = ()
    institutions: tuple[str, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    answer_key: AnswerKey = AnswerKey()
    # Populated only when a tool genuinely fetched this URL — never invented.
    # See docs/CONTENT_SPEC.md #6.1.
    source_url: str | None = None
    source_description: str | None = None


class KnowledgeDraftSchema(BaseModel):
    """What the authoring agent must return for a knowledge document draft.
    See docs/CONTENT_SPEC.md #6.3.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_]{3,64}$")
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(max_length=500)
    body_md: str = Field(max_length=200_000)
    modules: tuple[Module, ...] = ()
    topics: tuple[str, ...] = ()
    related_slugs: tuple[str, ...] = ()
    source_url: str | None = None
