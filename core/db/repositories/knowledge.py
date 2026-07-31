"""Knowledge document repository. The only place knowledge_docs is read from or
written to Postgres. Mirrors questions.py, since D12 governs both banks alike.
See docs/DATA_SPEC.md #5.6, #8.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, cast
from uuid import UUID

from core.db.errors import NotFound
from core.db.repositories.base import clamp_limit, translate_errors
from core.models.common import Page
from core.models.knowledge import KnowledgeDoc, KnowledgeDraft, KnowledgeFilters, KnowledgePatch

if TYPE_CHECKING:
    from collections.abc import Collection

    from supabase import Client

_TABLE = "knowledge_docs"


def _row_to_doc(row: Any) -> KnowledgeDoc:  # noqa: ANN401 - raw PostgREST JSON row
    return KnowledgeDoc.model_validate(row)


def _apply_filters(query: Any, filters: KnowledgeFilters) -> Any:  # noqa: ANN401
    if filters.tiers:
        query = query.in_("tier", [t.value for t in filters.tiers])
    if filters.modules:
        query = query.overlaps("modules", [m.value for m in filters.modules])
    if filters.topics:
        query = query.overlaps("topics", list(filters.topics))
    if filters.verification_levels:
        query = query.in_("verification_level", [v.value for v in filters.verification_levels])
    if filters.min_upvotes is not None:
        query = query.gte("upvotes", filters.min_upvotes)
    # mine_only is intentionally not applied here — it needs the caller's user
    # id, which this filter set does not carry. Callers scope to "mine" by
    # passing an explicit owner/author predicate at the call site instead.
    return query


class GroundingBundle(NamedTuple):
    """What the authoring agent injects into a prompt for selected documents.
    See docs/AI_SPEC.md #7 (defined here now so the Phase 2 agent work has a
    stable contract to build against; not yet called from anywhere).
    """

    docs: tuple[KnowledgeDoc, ...]
    total_token_estimate: int


class KnowledgeRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self, doc_id: UUID) -> KnowledgeDoc | None:
        def _do() -> KnowledgeDoc | None:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("id", str(doc_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return _row_to_doc(resp.data)

        return translate_errors(_do)

    def get_or_raise(self, doc_id: UUID) -> KnowledgeDoc:
        doc = self.get(doc_id)
        if doc is None:
            raise NotFound(f"knowledge document {doc_id} not found")
        return doc

    def get_by_slug(self, slug: str) -> KnowledgeDoc | None:
        def _do() -> KnowledgeDoc | None:
            resp = self._client.table(_TABLE).select("*").eq("slug", slug).maybe_single().execute()
            if resp is None or resp.data is None:
                return None
            return _row_to_doc(resp.data)

        return translate_errors(_do)

    def search(
        self,
        query: str | None = None,
        *,
        filters: KnowledgeFilters,
        limit: int = 25,
        offset: int = 0,
    ) -> Page[KnowledgeDoc]:
        limit = clamp_limit(limit)

        def _do() -> Page[KnowledgeDoc]:
            q = self._client.table(_TABLE).select("*", count=cast(Any, "exact"))
            q = _apply_filters(q, filters)
            if query:
                q = q.text_search("search_tsv", query)
            q = q.range(offset, offset + limit - 1)
            resp = q.execute()
            items = tuple(_row_to_doc(row) for row in resp.data)
            total = resp.count if resp.count is not None else len(items)
            return Page[KnowledgeDoc](items=items, total=total, offset=offset, limit=limit)

        return translate_errors(_do)

    def list_for_grounding(self, ids: Collection[UUID]) -> GroundingBundle:
        """Fetch selected documents for injection into an authoring prompt.
        RLS still applies via the caller's client, so this can never surface a
        document the requesting user could not open themselves — see
        docs/AI_SPEC.md #7.
        """
        if not ids:
            return GroundingBundle(docs=(), total_token_estimate=0)

        def _do() -> GroundingBundle:
            resp = self._client.table(_TABLE).select("*").in_("id", [str(i) for i in ids]).execute()
            docs = tuple(_row_to_doc(row) for row in resp.data)
            return GroundingBundle(
                docs=docs, total_token_estimate=sum(d.token_estimate for d in docs)
            )

        return translate_errors(_do)

    def create(self, draft: KnowledgeDraft, *, author_id: UUID) -> KnowledgeDoc:
        def _do() -> KnowledgeDoc:
            payload = draft.model_dump(mode="json", exclude_none=True)
            payload["author_id"] = str(author_id)
            if draft.tier.value == "private":
                payload["owner_id"] = str(author_id)
            resp = self._client.table(_TABLE).insert(payload).execute()
            return _row_to_doc(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def update(self, doc_id: UUID, patch: KnowledgePatch) -> KnowledgeDoc:
        def _do() -> KnowledgeDoc:
            payload = patch.model_dump(mode="json", exclude_none=True)
            resp = self._client.table(_TABLE).update(payload).eq("id", str(doc_id)).execute()
            if not resp.data:
                raise NotFound(f"knowledge document {doc_id} not found")
            return _row_to_doc(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def set_status(self, doc_id: UUID, status: str) -> None:
        def _do() -> None:
            self._client.table(_TABLE).update({"status": status}).eq("id", str(doc_id)).execute()

        translate_errors(_do)

    def set_tier(self, doc_id: UUID, tier: str) -> None:
        """Used by the "share with community" / "return to private" actions
        (tier flips a single row — no clone; see docs/CONTENT_SPEC.md #2).
        """

        def _do() -> None:
            self._client.table(_TABLE).update({"tier": tier}).eq("id", str(doc_id)).execute()

        translate_errors(_do)
