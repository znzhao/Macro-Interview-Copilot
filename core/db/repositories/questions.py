"""Question repository. The only place questions are read from or written to
Postgres. See docs/DATA_SPEC.md #8.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from core.db.errors import NotFound
from core.db.repositories.base import clamp_limit, translate_errors
from core.models.common import Page
from core.models.question import Question, QuestionDraft, QuestionFilters, QuestionPatch

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "questions"


def _row_to_question(row: Any) -> Question:  # noqa: ANN401 - raw PostgREST JSON row
    return Question.model_validate(row)


def _apply_filters(query: Any, filters: QuestionFilters) -> Any:  # noqa: ANN401
    if filters.tiers:
        query = query.in_("tier", [t.value for t in filters.tiers])
    if filters.modules:
        query = query.in_("module", [m.value for m in filters.modules])
    if filters.topics:
        query = query.in_("topic", list(filters.topics))
    if filters.difficulties:
        query = query.in_("difficulty", [d.value for d in filters.difficulties])
    if filters.institutions:
        query = query.overlaps("institutions", list(filters.institutions))
    if filters.target_roles:
        query = query.overlaps("target_roles", [r.value for r in filters.target_roles])
    if filters.verification_levels:
        query = query.in_("verification_level", [v.value for v in filters.verification_levels])
    if filters.min_upvotes is not None:
        query = query.gte("upvotes", filters.min_upvotes)
    if filters.has_answer_key:
        query = query.neq("answer_key", "{}")
    # mine_only is intentionally not applied here — see the identical note in
    # core/db/repositories/knowledge.py.
    return query


class QuestionRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self, question_id: UUID) -> Question | None:
        def _do() -> Question | None:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("id", str(question_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return _row_to_question(resp.data)

        return translate_errors(_do)

    def get_or_raise(self, question_id: UUID) -> Question:
        question = self.get(question_id)
        if question is None:
            raise NotFound(f"question {question_id} not found")
        return question

    def search(
        self,
        query: str | None = None,
        *,
        filters: QuestionFilters,
        limit: int = 25,
        offset: int = 0,
    ) -> Page[Question]:
        limit = clamp_limit(limit)

        def _do() -> Page[Question]:
            q = self._client.table(_TABLE).select("*", count=cast(Any, "exact"))
            q = _apply_filters(q, filters)
            if query:
                q = q.text_search("search_tsv", query)
            q = q.range(offset, offset + limit - 1)
            resp = q.execute()
            items = tuple(_row_to_question(row) for row in resp.data)
            total = resp.count if resp.count is not None else len(items)
            return Page[Question](items=items, total=total, offset=offset, limit=limit)

        return translate_errors(_do)

    def list_for_selection(
        self,
        *,
        filters: QuestionFilters,
        exclude_ids: Collection[UUID],
        limit: int,
    ) -> list[Question]:
        limit = clamp_limit(limit)

        def _do() -> list[Question]:
            q = self._client.table(_TABLE).select("*")
            q = _apply_filters(q, filters)
            if exclude_ids:
                q = q.not_.in_("id", [str(i) for i in exclude_ids])
            q = q.limit(limit)
            resp = q.execute()
            return [_row_to_question(row) for row in resp.data]

        return translate_errors(_do)

    def create(self, draft: QuestionDraft, *, author_id: UUID) -> Question:
        def _do() -> Question:
            payload = draft.model_dump(mode="json", exclude_none=True)
            payload["author_id"] = str(author_id)
            if draft.tier.value == "private":
                payload["owner_id"] = str(author_id)
            resp = self._client.table(_TABLE).insert(payload).execute()
            return _row_to_question(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def update(self, question_id: UUID, patch: QuestionPatch) -> Question:
        def _do() -> Question:
            payload = patch.model_dump(mode="json", exclude_none=True)
            resp = self._client.table(_TABLE).update(payload).eq("id", str(question_id)).execute()
            if not resp.data:
                raise NotFound(f"question {question_id} not found")
            return _row_to_question(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def set_status(self, question_id: UUID, status: str) -> None:
        def _do() -> None:
            self._client.table(_TABLE).update({"status": status}).eq(
                "id", str(question_id)
            ).execute()

        translate_errors(_do)

    def set_tier(self, question_id: UUID, tier: str) -> None:
        """Used by the "share with community" / "return to private" actions
        (tier flips a single row — no clone; see docs/CONTENT_SPEC.md #2).
        Promotion to verified is a separate act — see ReviewRepository.approve.
        """

        def _do() -> None:
            self._client.table(_TABLE).update({"tier": tier}).eq("id", str(question_id)).execute()

        translate_errors(_do)

    # Voting moved to VoteRepository in Phase 2 (core/db/repositories/votes.py),
    # since votes are now ±1 and shared between both banks rather than a single
    # question-only upvote insert. The old insert here also relied on a DB
    # DEFAULT 1 on question_votes.value that migration 0003 removed.
