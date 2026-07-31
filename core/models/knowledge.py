"""Knowledge document domain models. See docs/DATA_SPEC.md #5.6, #10.2 and
docs/DECISIONS.md D12.

Governed identically to questions — same three tiers, same lifecycle, same
soft-delete rule — because D12 deliberately made this the second bank rather
than a bespoke design. slug is the join key evaluations.suggested_readings
points at (AI_SPEC not yet wired — Phase 3), so it is immutable and a document
is never hard-deleted; a stored evaluation may reference it for years.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from core.models.enums import Module, QuestionStatus, QuestionTier, VerificationLevel

_SLUG_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")


class KnowledgeDoc(BaseModel):
    """A read model. Every DB read of a knowledge document passes through this."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    slug: str
    tier: QuestionTier
    status: QuestionStatus
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(max_length=500)
    body_md: str = Field(max_length=200_000)
    modules: tuple[Module, ...] = ()
    topics: tuple[str, ...] = ()
    related_slugs: tuple[str, ...] = ()
    verification_level: VerificationLevel
    source_url: HttpUrl | None = None
    origin: str = "uploaded"
    author_id: UUID | None = None
    owner_id: UUID | None = None
    source_doc_id: UUID | None = None
    upvotes: int = 0
    downvotes: int = 0
    token_estimate: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError(f"slug {value!r} must match ^[a-z0-9_]{{3,64}}$")
        return value

    @field_validator("origin")
    @classmethod
    def _origin_is_known(cls, value: str) -> str:
        if value not in ("uploaded", "ai_generated", "seeded"):
            raise ValueError(f"unknown origin {value!r}")
        return value

    @model_validator(mode="after")
    def _private_requires_owner(self) -> KnowledgeDoc:
        if self.tier is QuestionTier.PRIVATE and self.owner_id is None:
            raise ValueError("private knowledge documents require owner_id")
        return self


class KnowledgeDraft(BaseModel):
    """A write model for creating a new knowledge document."""

    model_config = ConfigDict(frozen=True)

    slug: str
    tier: QuestionTier
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(max_length=500)
    body_md: str = Field(max_length=200_000)
    modules: tuple[Module, ...] = ()
    topics: tuple[str, ...] = ()
    related_slugs: tuple[str, ...] = ()
    verification_level: VerificationLevel
    source_url: HttpUrl | None = None
    origin: str = "uploaded"

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError(f"slug {value!r} must match ^[a-z0-9_]{{3,64}}$")
        return value


class KnowledgePatch(BaseModel):
    """A partial update. Unset fields are left unchanged by the repository.

    slug is deliberately absent — it is immutable after insert (see module
    docstring); there is no supported way to rename one.
    """

    model_config = ConfigDict(frozen=True)

    title: str | None = Field(default=None, min_length=3, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body_md: str | None = Field(default=None, max_length=200_000)
    modules: tuple[Module, ...] | None = None
    topics: tuple[str, ...] | None = None
    related_slugs: tuple[str, ...] | None = None
    verification_level: VerificationLevel | None = None
    source_url: HttpUrl | None = None


class KnowledgeFilters(BaseModel):
    """Typed filter set. Translated to a parameterized query by the repository."""

    model_config = ConfigDict(frozen=True)

    tiers: tuple[QuestionTier, ...] = ()
    modules: tuple[Module, ...] = ()
    topics: tuple[str, ...] = ()
    verification_levels: tuple[VerificationLevel, ...] = ()
    min_upvotes: int | None = None
    mine_only: bool = False
