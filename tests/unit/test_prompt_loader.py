"""Unit tests for core.prompts.loader. See docs/IMPLEMENTATION_GUIDE.md #5.1."""

from __future__ import annotations

import hashlib

import pytest

from core.prompts.loader import PromptNotFound, load_prompt


def test_missing_prompt_file_raises() -> None:
    with pytest.raises(PromptNotFound):
        load_prompt("does_not_exist", "v1")


def test_question_author_v1_declares_expected_variables() -> None:
    spec = load_prompt("question_author", "v1")
    assert spec.name == "question_author"
    assert spec.version == "v1"
    expected = {"module", "topic", "difficulty", "target_role", "institution", "seed_context"}
    assert spec.variables == expected


def test_sha256_matches_file_contents() -> None:
    spec = load_prompt("question_author", "v1")
    assert spec.sha256 == hashlib.sha256(spec.template.encode("utf-8")).hexdigest()


def test_render_raises_on_missing_variable() -> None:
    spec = load_prompt("question_author", "v1")
    with pytest.raises(ValueError, match="missing required variables"):
        spec.render(module="Inflation", topic="Inflation Dynamics")


def test_render_substitutes_all_declared_variables() -> None:
    spec = load_prompt("question_author", "v1")
    rendered = spec.render(
        module="Inflation",
        topic="Inflation Dynamics",
        difficulty="hard",
        target_role="global_macro_hf",
        institution="",
        seed_context="",
    )
    assert "Inflation Dynamics" in rendered
    assert "{topic}" not in rendered


def test_author_agent_v1_has_no_declared_variables() -> None:
    # A static system prompt for the agent loop — no per-request templating.
    spec = load_prompt("author_agent", "v1")
    assert spec.variables == frozenset()
    assert spec.render() == spec.template


def test_knowledge_author_v1_declares_expected_variables() -> None:
    spec = load_prompt("knowledge_author", "v1")
    assert spec.variables == {"topic", "material"}


def test_load_prompt_is_cached_by_name_and_version() -> None:
    a = load_prompt("question_author", "v1")
    b = load_prompt("question_author", "v1")
    assert a is b
