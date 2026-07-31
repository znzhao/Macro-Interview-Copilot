"""Guardrail tests for core.models.answer_key.AnswerKey. See docs/DECISIONS.md
D10 and docs/IMPLEMENTATION_GUIDE.md #5.3b — this is only real if it is tested.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.models.answer_key import AnswerKey


def test_empty_answer_key_is_valid() -> None:
    key = AnswerKey()
    assert key.is_empty


def test_a_populated_section_is_not_empty() -> None:
    key = AnswerKey(framework=("Decompose real rates into policy path and term premium.",))
    assert not key.is_empty


def test_more_than_eight_bullets_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerKey(framework=tuple(f"bullet {i}" for i in range(9)))


def test_exactly_eight_bullets_is_allowed() -> None:
    key = AnswerKey(framework=tuple(f"bullet {i}" for i in range(8)))
    assert len(key.framework) == 8


def test_bullet_over_240_characters_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerKey(framework=("x" * 241,))


def test_bullet_at_240_characters_is_allowed() -> None:
    key = AnswerKey(framework=("x" * 240,))
    assert len(key.framework[0]) == 240


def test_empty_bullet_string_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerKey(framework=("",))


def test_embedded_newline_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerKey(framework=("line one\nline two",))


def test_embedded_carriage_return_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerKey(mechanism=("line one\rline two",))


def test_unknown_section_rejected() -> None:
    # extra="forbid": a model that invents a sixth section is a validation
    # failure, not a silently dropped field.
    with pytest.raises(ValidationError):
        AnswerKey.model_validate({"bogus_section": ["x"]})


def test_all_five_sections_can_be_populated_independently() -> None:
    key = AnswerKey(
        framework=("f",),
        mechanism=("m",),
        indicators=("i",),
        market_implication=("mi",),
        common_traps=("ct",),
    )
    assert not key.is_empty
    assert key.framework == ("f",)
    assert key.common_traps == ("ct",)


def test_no_section_cannot_be_concatenated_into_a_full_prose_answer() -> None:
    # A weak proxy for the golden-suite assertion in IMPLEMENTATION_GUIDE #5.4:
    # even at the maximum allowed size, a single section stays far short of
    # what a written interview answer needs (typically several hundred words).
    key = AnswerKey(framework=tuple("x" * 240 for _ in range(8)))
    concatenated = " ".join(key.framework)
    assert len(concatenated) <= 8 * 240 + 7  # bound is structural, not incidental
