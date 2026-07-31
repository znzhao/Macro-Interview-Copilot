"""Vote repository, for both banks. Upsert +/-1 and clear. See docs/DATA_SPEC.md
#5.2, #8.3.

Changing your mind is an UPDATE of the existing row (the composite PK is
(target_id, user_id)), not a second insert — supabase-py's upsert() covers
both the first vote and a later flip in one call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from core.db.repositories.base import translate_errors

if TYPE_CHECKING:
    from supabase import Client

VoteValue = Literal[-1, 1]


class VoteRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    # ── questions ────────────────────────────────────────────────────────
    def get_question_vote(self, question_id: UUID, user_id: UUID) -> VoteValue | None:
        def _do() -> VoteValue | None:
            resp = (
                self._client.table("question_votes")
                .select("value")
                .eq("question_id", str(question_id))
                .eq("user_id", str(user_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return cast(dict[str, Any], resp.data)["value"]  # type: ignore[no-any-return]

        return translate_errors(_do)

    def set_question_vote(self, question_id: UUID, user_id: UUID, value: VoteValue) -> None:
        def _do() -> None:
            self._client.table("question_votes").upsert(
                {"question_id": str(question_id), "user_id": str(user_id), "value": value},
                on_conflict="question_id,user_id",
            ).execute()

        translate_errors(_do)

    def clear_question_vote(self, question_id: UUID, user_id: UUID) -> None:
        def _do() -> None:
            self._client.table("question_votes").delete().eq("question_id", str(question_id)).eq(
                "user_id", str(user_id)
            ).execute()

        translate_errors(_do)

    # ── knowledge ────────────────────────────────────────────────────────
    def get_knowledge_vote(self, doc_id: UUID, user_id: UUID) -> VoteValue | None:
        def _do() -> VoteValue | None:
            resp = (
                self._client.table("knowledge_votes")
                .select("value")
                .eq("doc_id", str(doc_id))
                .eq("user_id", str(user_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return cast(dict[str, Any], resp.data)["value"]  # type: ignore[no-any-return]

        return translate_errors(_do)

    def set_knowledge_vote(self, doc_id: UUID, user_id: UUID, value: VoteValue) -> None:
        def _do() -> None:
            self._client.table("knowledge_votes").upsert(
                {"doc_id": str(doc_id), "user_id": str(user_id), "value": value},
                on_conflict="doc_id,user_id",
            ).execute()

        translate_errors(_do)

    def clear_knowledge_vote(self, doc_id: UUID, user_id: UUID) -> None:
        def _do() -> None:
            self._client.table("knowledge_votes").delete().eq("doc_id", str(doc_id)).eq(
                "user_id", str(user_id)
            ).execute()

        translate_errors(_do)
