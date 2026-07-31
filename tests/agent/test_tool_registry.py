"""Unit tests for core.agent.tools.registry — the closed tool set and its
dispatcher. See docs/AI_SPEC.md #7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.agent.errors import ToolBlocked
from core.agent.tools.registry import TOOL_NAMES, TOOL_SPECS, ToolContext, execute_tool
from core.agent.tools.uploads import Upload
from core.db.errors import NotFound
from core.llm.errors import LLMToolArgError
from core.models.common import Page
from core.models.knowledge import KnowledgeDoc


def _make_doc(**overrides: object) -> KnowledgeDoc:
    kwargs = dict(
        id=uuid4(),
        slug="yield_curve",
        tier="verified",
        status="published",
        title="The Yield Curve",
        summary="A short summary.",
        body_md="## Definition\nThe yield curve is...",
        verification_level="ai_generated",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    kwargs.update(overrides)
    return KnowledgeDoc(**kwargs)  # type: ignore[arg-type]


class _FakeKnowledgeRepo:
    def __init__(self, docs: list[KnowledgeDoc]) -> None:
        self._docs = docs

    def search(
        self, query: str | None = None, *, filters: object, limit: int = 25
    ) -> Page[KnowledgeDoc]:
        items = tuple(self._docs[:limit])
        return Page[KnowledgeDoc](items=items, total=len(items), offset=0, limit=limit)

    def get_by_slug(self, slug: str) -> KnowledgeDoc | None:
        return next((d for d in self._docs if d.slug == slug), None)


@pytest.fixture()
def context() -> ToolContext:
    repo = _FakeKnowledgeRepo([_make_doc()])
    uploads = {"u1": Upload(filename="notes.md", text="Some uploaded notes.")}
    return ToolContext(knowledge_repo=repo, uploads=uploads)  # type: ignore[arg-type]


def test_tool_specs_cover_exactly_the_four_documented_tools() -> None:
    assert set(TOOL_NAMES) == {"search_knowledge", "read_knowledge", "fetch_url", "read_upload"}
    assert len(TOOL_SPECS) == 4


def test_search_knowledge_dispatch(context: ToolContext) -> None:
    content = execute_tool("search_knowledge", {"query": "yield"}, context)
    results = json.loads(content)
    assert results == [
        {"slug": "yield_curve", "title": "The Yield Curve", "summary": "A short summary."}
    ]


def test_search_knowledge_missing_query_raises_arg_error(context: ToolContext) -> None:
    with pytest.raises(LLMToolArgError, match="query"):
        execute_tool("search_knowledge", {}, context)


def test_read_knowledge_dispatch(context: ToolContext) -> None:
    content = execute_tool("read_knowledge", {"slug": "yield_curve"}, context)
    data = json.loads(content)
    assert data["title"] == "The Yield Curve"
    assert "yield curve is" in data["body_md"]


def test_read_knowledge_not_found_propagates(context: ToolContext) -> None:
    with pytest.raises(NotFound):
        execute_tool("read_knowledge", {"slug": "does_not_exist"}, context)


def test_read_upload_dispatch(context: ToolContext) -> None:
    content = execute_tool("read_upload", {"upload_id": "u1"}, context)
    data = json.loads(content)
    assert data == {"filename": "notes.md", "text": "Some uploaded notes.", "truncated": False}


def test_read_upload_missing_id_is_tool_blocked(context: ToolContext) -> None:
    with pytest.raises(ToolBlocked):
        execute_tool("read_upload", {"upload_id": "nope"}, context)


def test_fetch_url_missing_arg_raises_arg_error(context: ToolContext) -> None:
    with pytest.raises(LLMToolArgError, match="url"):
        execute_tool("fetch_url", {}, context)


def test_fetch_url_disallowed_scheme_is_tool_blocked(context: ToolContext) -> None:
    with pytest.raises(ToolBlocked):
        execute_tool("fetch_url", {"url": "file:///etc/passwd"}, context)


def test_unknown_tool_raises_arg_error(context: ToolContext) -> None:
    with pytest.raises(LLMToolArgError, match="unknown tool"):
        execute_tool("delete_everything", {}, context)


def test_long_knowledge_body_is_truncated_for_the_model(context: ToolContext) -> None:
    long_doc = _make_doc(slug="long_doc", body_md="x" * 30_000)
    repo = _FakeKnowledgeRepo([long_doc])
    ctx = ToolContext(knowledge_repo=repo, uploads={})  # type: ignore[arg-type]
    content = execute_tool("read_knowledge", {"slug": "long_doc"}, ctx)
    data = json.loads(content)
    assert data["truncated"] is True
    assert len(data["body_md"]) == 20_000
