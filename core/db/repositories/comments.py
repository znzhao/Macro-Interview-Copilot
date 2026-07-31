"""Comment repository. One-level threading. See docs/DATA_SPEC.md #5.8, #8.3.

Deletion is a tombstone (is_deleted=true via UPDATE), never a real DELETE —
so replies are never orphaned. There is no delete() method here at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from core.db.errors import NotFound
from core.db.repositories.base import translate_errors
from core.models.social import Comment, CommentDraft, ContentKind

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "comments"


def _row_to_comment(row: Any) -> Comment:  # noqa: ANN401 - raw PostgREST JSON row
    return Comment.model_validate(row)


class CommentRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list_for_target(self, kind: ContentKind, target_id: UUID) -> list[Comment]:
        """Top-level comments and their replies in a single query — grouping
        by parent_id is the caller's job, so no page ever pays for N+1 round
        trips to render one thread.
        """
        column = "question_id" if kind is ContentKind.QUESTION else "doc_id"

        def _do() -> list[Comment]:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq(column, str(target_id))
                .order("created_at")
                .execute()
            )
            return [_row_to_comment(row) for row in resp.data]

        return translate_errors(_do)

    def post(self, draft: CommentDraft, *, author_id: UUID) -> Comment:
        def _do() -> Comment:
            payload = draft.model_dump(mode="json", exclude_none=True)
            payload["author_id"] = str(author_id)
            resp = self._client.table(_TABLE).insert(payload).execute()
            return _row_to_comment(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def update_body(self, comment_id: UUID, *, body: str) -> Comment:
        def _do() -> Comment:
            resp = (
                self._client.table(_TABLE)
                .update({"body": body})
                .eq("id", str(comment_id))
                .execute()
            )
            if not resp.data:
                raise NotFound(f"comment {comment_id} not found")
            return _row_to_comment(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def tombstone(self, comment_id: UUID) -> None:
        """Author or admin only — enforced by RLS, not here."""

        def _do() -> None:
            self._client.table(_TABLE).update({"is_deleted": True}).eq(
                "id", str(comment_id)
            ).execute()

        translate_errors(_do)
