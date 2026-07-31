"""Unit tests for core.models.knowledge. No network, no database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.models.enums import Module, QuestionStatus, QuestionTier, VerificationLevel
from core.models.knowledge import KnowledgeDoc, KnowledgeDraft


def _base_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        id=uuid4(),
        slug="yield_curve",
        tier=QuestionTier.VERIFIED,
        status=QuestionStatus.PUBLISHED,
        title="The Yield Curve",
        summary="A short summary of the yield curve.",
        body_md="## Definition\nThe yield curve is...",
        modules=(Module.RATES_YIELD_CURVE,),
        verification_level=VerificationLevel.AI_GENERATED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_verified_doc_constructs_without_a_source() -> None:
    # D11 applies to knowledge exactly as it does to questions: no source
    # requirement at any tier.
    doc = KnowledgeDoc(**_base_kwargs())
    assert doc.tier is QuestionTier.VERIFIED
    assert doc.source_url is None


def test_private_without_owner_rejected() -> None:
    with pytest.raises(ValidationError, match="owner_id"):
        KnowledgeDoc(**_base_kwargs(tier=QuestionTier.PRIVATE, owner_id=None))


def test_private_with_owner_is_allowed() -> None:
    doc = KnowledgeDoc(**_base_kwargs(tier=QuestionTier.PRIVATE, owner_id=uuid4()))
    assert doc.tier is QuestionTier.PRIVATE


@pytest.mark.parametrize(
    "bad_slug", ["ab", "Has-Upper", "has space", "has-hyphen", "x" * 65, "semi;colon"]
)
def test_malformed_slug_rejected(bad_slug: str) -> None:
    with pytest.raises(ValidationError, match="slug"):
        KnowledgeDoc(**_base_kwargs(slug=bad_slug))


def test_slug_at_boundaries_is_allowed() -> None:
    assert KnowledgeDoc(**_base_kwargs(slug="abc")).slug == "abc"
    assert KnowledgeDoc(**_base_kwargs(slug="a" * 64)).slug == "a" * 64


def test_title_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDoc(**_base_kwargs(title="ab"))


def test_summary_over_limit_rejected() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDoc(**_base_kwargs(summary="x" * 501))


def test_unknown_origin_rejected() -> None:
    with pytest.raises(ValidationError, match="origin"):
        KnowledgeDoc(**_base_kwargs(origin="hand_waved"))


def test_draft_requires_valid_slug() -> None:
    with pytest.raises(ValidationError, match="slug"):
        KnowledgeDraft(
            slug="BAD SLUG",
            tier=QuestionTier.PRIVATE,
            title="Title",
            summary="Summary",
            body_md="Body",
            verification_level=VerificationLevel.AI_GENERATED,
        )
