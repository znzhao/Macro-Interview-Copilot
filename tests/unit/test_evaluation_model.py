"""Unit tests for core.models.evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.models.evaluation import Evaluation


def _base_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        id=uuid4(),
        turn_id=uuid4(),
        user_id=uuid4(),
        score_framework=3,
        score_logic=3,
        score_evidence=2,
        score_market=3,
        score_communication=4,
        total_score=70,
        model="claude-sonnet-5",
        prompt_version="evaluator.v1",
        created_at=datetime.now(UTC),
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_evaluation_constructs() -> None:
    ev = Evaluation(**_base_kwargs())
    assert ev.dimension_scores["framework"] == 3


def test_dimension_score_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        Evaluation(**_base_kwargs(score_framework=5))


def test_unknown_justification_key_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown dimension keys"):
        Evaluation(**_base_kwargs(justifications={"not_a_dimension": "text"}))


def test_known_justification_key_accepted() -> None:
    ev = Evaluation(**_base_kwargs(justifications={"framework": "Clear structure."}))
    assert ev.justifications["framework"] == "Clear structure."
