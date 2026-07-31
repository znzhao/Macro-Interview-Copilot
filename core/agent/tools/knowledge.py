"""search_knowledge and read_knowledge tools. See docs/AI_SPEC.md #7.

Both run through the caller's own KnowledgeRepository — i.e. the caller's
Supabase client, carrying the caller's own JWT — so RLS decides what is
visible. The agent must never surface a document its operator could not open
themselves; that guarantee lives entirely in which repository instance gets
passed in here, not in anything this module does.
"""

from __future__ import annotations

from core.db.errors import NotFound
from core.db.repositories.knowledge import KnowledgeRepository
from core.models.knowledge import KnowledgeFilters

_MAX_SEARCH_LIMIT = 10


def search_knowledge(repo: KnowledgeRepository, query: str, limit: int = 5) -> list[dict[str, str]]:
    """Summaries only — full text costs tokens and is what read_knowledge is for."""
    bounded_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
    page = repo.search(query, filters=KnowledgeFilters(), limit=bounded_limit)
    return [{"slug": doc.slug, "title": doc.title, "summary": doc.summary} for doc in page.items]


def read_knowledge(repo: KnowledgeRepository, slug: str) -> dict[str, str]:
    doc = repo.get_by_slug(slug)
    if doc is None:
        raise NotFound(f"no knowledge document with slug {slug!r} is visible to you")
    return {"title": doc.title, "body_md": doc.body_md}
