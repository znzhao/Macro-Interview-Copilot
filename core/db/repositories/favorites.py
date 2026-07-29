"""Favorites repository. See docs/DATA_SPEC.md #5.4, #8."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.db.repositories.base import translate_errors
from core.models.profile import Favorite

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "favorites"


class FavoriteRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list_for_user(self, user_id: UUID) -> list[Favorite]:
        def _do() -> list[Favorite]:
            resp = (
                self._client.table(_TABLE).select("*").eq("user_id", str(user_id)).execute()
            )
            return [Favorite.model_validate(row) for row in resp.data]

        return translate_errors(_do)

    def add(self, user_id: UUID, question_id: UUID) -> None:
        def _do() -> None:
            self._client.table(_TABLE).upsert(
                {"user_id": str(user_id), "question_id": str(question_id)},
                on_conflict="user_id,question_id",
            ).execute()

        translate_errors(_do)

    def remove(self, user_id: UUID, question_id: UUID) -> None:
        def _do() -> None:
            self._client.table(_TABLE).delete().eq("user_id", str(user_id)).eq(
                "question_id", str(question_id)
            ).execute()

        translate_errors(_do)
