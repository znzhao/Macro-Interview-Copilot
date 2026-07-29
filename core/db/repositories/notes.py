"""Notes repository. See docs/DATA_SPEC.md #5.4, #8."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.db.repositories.base import translate_errors
from core.models.profile import Note

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "notes"


class NoteRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get_for_question(self, user_id: UUID, question_id: UUID) -> Note | None:
        def _do() -> Note | None:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", str(user_id))
                .eq("question_id", str(question_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return Note.model_validate(resp.data)

        return translate_errors(_do)

    def upsert(self, user_id: UUID, question_id: UUID, content: str) -> Note:
        def _do() -> Note:
            resp = (
                self._client.table(_TABLE)
                .upsert(
                    {
                        "user_id": str(user_id),
                        "question_id": str(question_id),
                        "content": content,
                    },
                    on_conflict="user_id,question_id",
                )
                .execute()
            )
            return Note.model_validate(resp.data[0])

        return translate_errors(_do)

    def delete(self, user_id: UUID, question_id: UUID) -> None:
        def _do() -> None:
            self._client.table(_TABLE).delete().eq("user_id", str(user_id)).eq(
                "question_id", str(question_id)
            ).execute()

        translate_errors(_do)
