"""Question domain models. See docs/DATA_SPEC.md #3 and #10."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from core.models.answer_key import AnswerKey
from core.models.enums import (
    TOPICS_BY_MODULE,
    Difficulty,
    Frequency,
    Module,
    QuestionStatus,
    QuestionTier,
    TargetRole,
    VerificationLevel,
)


class SecondarySource(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    url: HttpUrl


def _check_topic(module: Module, topic: str) -> None:
    if topic not in TOPICS_BY_MODULE[module]:
        raise ValueError(f"topic {topic!r} is not valid for module {module!r}")


class Question(BaseModel):
    """A read model. Every DB read of a question passes through this."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    ref: str
    tier: QuestionTier
    status: QuestionStatus
    module: Module
    topic: str
    question: str = Field(min_length=20, max_length=1200)
    difficulty: Difficulty
    frequency: Frequency | None = None
    target_roles: tuple[TargetRole, ...] = ()
    institutions: tuple[str, ...] = ()
    verification_level: VerificationLevel
    source_description: str | None = None
    source_url: HttpUrl | None = None
    secondary_sources: tuple[SecondarySource, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    answer_key: AnswerKey = AnswerKey()
    author_id: UUID | None = None
    owner_id: UUID | None = None
    source_question_id: UUID | None = None
    upvotes: int = 0
    downvotes: int = 0
    created_at: datetime
    updated_at: datetime

    # _verified_requires_source was removed under D11: verified now means "an
    # admin reviewed this and vouches for its quality", not traceable
    # provenance. The CHECK constraint it mirrored (verified_needs_source) was
    # dropped in core/db/migrations/0003_content_governance.sql for the same
    # reason — it made AI-authored questions permanently un-promotable.
    # Provenance lives entirely in verification_level now.

    @model_validator(mode="after")
    def _private_requires_owner(self) -> Question:
        if self.tier is QuestionTier.PRIVATE and self.owner_id is None:
            raise ValueError("private questions require owner_id")
        return self

    @model_validator(mode="after")
    def _topic_belongs_to_module(self) -> Question:
        _check_topic(self.module, self.topic)
        return self


class QuestionDraft(BaseModel):
    """A write model for creating a new question. No id, no server-assigned fields."""

    model_config = ConfigDict(frozen=True)

    tier: QuestionTier
    module: Module
    topic: str
    question: str = Field(min_length=20, max_length=1200)
    difficulty: Difficulty
    frequency: Frequency | None = None
    target_roles: tuple[TargetRole, ...] = ()
    institutions: tuple[str, ...] = ()
    verification_level: VerificationLevel
    source_description: str | None = None
    source_url: HttpUrl | None = None
    secondary_sources: tuple[SecondarySource, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    answer_key: AnswerKey = AnswerKey()

    # No verified/source validator here either — see the note on Question. A
    # draft may target tier=verified with no source_url; only is_admin() (RLS)
    # gates who may actually write tier='verified'.

    @model_validator(mode="after")
    def _topic_belongs_to_module(self) -> QuestionDraft:
        _check_topic(self.module, self.topic)
        return self


class QuestionPatch(BaseModel):
    """A partial update. Unset fields are left unchanged by the repository."""

    model_config = ConfigDict(frozen=True)

    module: Module | None = None
    topic: str | None = None
    question: str | None = Field(default=None, min_length=20, max_length=1200)
    difficulty: Difficulty | None = None
    frequency: Frequency | None = None
    target_roles: tuple[TargetRole, ...] | None = None
    institutions: tuple[str, ...] | None = None
    verification_level: VerificationLevel | None = None
    source_description: str | None = None
    source_url: HttpUrl | None = None
    secondary_sources: tuple[SecondarySource, ...] | None = None
    follow_up_questions: tuple[str, ...] | None = None
    answer_key: AnswerKey | None = None

    @model_validator(mode="after")
    def _topic_requires_module_context(self) -> QuestionPatch:
        # A topic-only patch cannot be validated against the vocabulary here because
        # the module isn't known without the existing row. The repository layer is
        # responsible for re-validating the merged result as a full Question.
        return self


class QuestionFilters(BaseModel):
    """Typed filter set. Translated to a parameterized query by the repository."""

    model_config = ConfigDict(frozen=True)

    tiers: tuple[QuestionTier, ...] = ()
    modules: tuple[Module, ...] = ()
    topics: tuple[str, ...] = ()
    difficulties: tuple[Difficulty, ...] = ()
    institutions: tuple[str, ...] = ()
    target_roles: tuple[TargetRole, ...] = ()
    verification_levels: tuple[VerificationLevel, ...] = ()
    min_upvotes: int | None = None
    favorited_only: bool = False
    unattempted_only: bool = False
    mine_only: bool = False
    has_answer_key: bool = False
