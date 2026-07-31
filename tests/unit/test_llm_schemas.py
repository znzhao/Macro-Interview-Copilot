"""Unit tests for core.llm.schemas — the authoring agent's structured-output
contracts. See docs/AI_SPEC.md #2.2, #6.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.llm.schemas import KnowledgeDraftSchema, QuestionDraftSchema


def test_question_draft_minimal_valid() -> None:
    draft = QuestionDraftSchema(
        module="Inflation",
        topic="Inflation Dynamics",
        question="Why can inflation remain persistent despite restrictive policy?",
        difficulty="hard",
    )
    assert draft.answer_key.is_empty
    assert draft.source_url is None


def test_question_draft_with_answer_key() -> None:
    draft = QuestionDraftSchema(
        module="Inflation",
        topic="Inflation Dynamics",
        question="Why can inflation remain persistent despite restrictive policy?",
        difficulty="hard",
        answer_key={"framework": ["decompose supply vs demand drivers"]},
    )
    assert draft.answer_key.framework == ("decompose supply vs demand drivers",)


def test_question_draft_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        QuestionDraftSchema.model_validate(
            {
                "module": "Inflation",
                "topic": "Inflation Dynamics",
                "question": "Why can inflation remain persistent despite restrictive policy?",
                "difficulty": "hard",
                "model_answer": "a full prose answer the model snuck in",
            }
        )


def test_question_draft_rejects_invalid_module() -> None:
    with pytest.raises(ValidationError):
        QuestionDraftSchema(
            module="Not A Real Module",
            topic="x",
            question="x" * 30,
            difficulty="hard",
        )


def test_question_draft_json_schema_has_no_ungoverned_fields() -> None:
    # Governance fields (tier, status, author_id, owner_id, verification_level)
    # are assigned by the caller, never by the model — docs/llm/schemas.py.
    schema = QuestionDraftSchema.model_json_schema()
    for forbidden in ("tier", "status", "author_id", "owner_id", "verification_level"):
        assert forbidden not in schema["properties"]


def test_knowledge_draft_minimal_valid() -> None:
    draft = KnowledgeDraftSchema(
        slug="yield_curve",
        title="The Yield Curve",
        summary="A short summary.",
        body_md="## Definition\nThe yield curve is...",
    )
    assert draft.slug == "yield_curve"


def test_knowledge_draft_rejects_malformed_slug() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDraftSchema(
            slug="Not A Slug!",
            title="Title",
            summary="Summary",
            body_md="Body",
        )


def test_knowledge_draft_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        KnowledgeDraftSchema.model_validate(
            {
                "slug": "yield_curve",
                "title": "The Yield Curve",
                "summary": "Summary",
                "body_md": "Body",
                "author_id": "should-not-be-here",
            }
        )
