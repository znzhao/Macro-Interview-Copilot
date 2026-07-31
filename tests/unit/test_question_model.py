"""Unit tests for core.models.question. No network, no database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.models.enums import (
    Difficulty,
    Module,
    QuestionStatus,
    QuestionTier,
    VerificationLevel,
)
from core.models.question import Question, QuestionDraft


def _base_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        id=uuid4(),
        ref="Q0001",
        tier=QuestionTier.VERIFIED,
        status=QuestionStatus.PUBLISHED,
        module=Module.INFLATION,
        topic="Inflation Dynamics",
        question="Why can inflation remain persistent despite restrictive policy?",
        difficulty=Difficulty.HARD,
        verification_level=VerificationLevel.VERIFIED_INTERVIEW,
        source_url="https://www.imf.org",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_verified_question_constructs() -> None:
    q = Question(**_base_kwargs())
    assert q.tier is QuestionTier.VERIFIED


def test_verified_without_source_url_is_allowed() -> None:
    # D11: verified now means "an admin vouches for this", not traceable
    # provenance — dropping the requirement is what makes AI-authored
    # questions promotable at all. Provenance still shows up via
    # verification_level, just not enforced as a presence check here.
    q = Question(**_base_kwargs(source_url=None, verification_level=VerificationLevel.AI_GENERATED))
    assert q.source_url is None
    assert q.tier is QuestionTier.VERIFIED


def test_private_without_owner_rejected() -> None:
    with pytest.raises(ValidationError, match="owner_id"):
        Question(
            **_base_kwargs(
                tier=QuestionTier.PRIVATE,
                verification_level=VerificationLevel.AI_GENERATED,
                source_url=None,
                owner_id=None,
            )
        )


def test_topic_must_belong_to_module() -> None:
    with pytest.raises(ValidationError, match="not valid for module"):
        Question(**_base_kwargs(module=Module.FX, topic="Inflation Dynamics"))


def test_question_length_bounds() -> None:
    with pytest.raises(ValidationError):
        Question(**_base_kwargs(question="too short"))


def test_draft_verified_without_source_is_allowed() -> None:
    # D11: the Pydantic-level requirement was removed along with the DB CHECK.
    # Who may actually persist tier='verified' is enforced by RLS (is_admin()),
    # not by this model.
    draft = QuestionDraft(
        tier=QuestionTier.VERIFIED,
        module=Module.INFLATION,
        topic="Inflation Dynamics",
        question="Why can inflation remain persistent despite restrictive policy?",
        difficulty=Difficulty.HARD,
        verification_level=VerificationLevel.AI_GENERATED,
        source_url=None,
    )
    assert draft.source_url is None


def test_community_draft_without_source_is_allowed() -> None:
    draft = QuestionDraft(
        tier=QuestionTier.COMMUNITY,
        module=Module.FX,
        topic="Carry Trade",
        question="How would you construct a carry trade in the current regime?",
        difficulty=Difficulty.MEDIUM,
        verification_level=VerificationLevel.AI_GENERATED,
        source_url=None,
    )
    assert draft.source_url is None
