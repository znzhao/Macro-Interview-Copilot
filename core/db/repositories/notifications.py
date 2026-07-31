"""Notification repository. See docs/DATA_SPEC.md #5.9, #8.3 and docs/DECISIONS.md D15.

Deliberately has no create()/insert method of any kind. Rows are written
exclusively by SECURITY DEFINER triggers and functions in
core/db/migrations/0005_phase2_rls.sql — RLS denies every client-side INSERT
on this table (see that file's comment on notifications_select). A repository
that could insert a notification would be a way to accidentally reintroduce
the forged-notification hole the schema was built to close.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from core.db.repositories.base import clamp_limit, translate_errors
from core.models.common import Page
from core.models.social import Notification

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "notifications"


def _row_to_notification(row: Any) -> Notification:  # noqa: ANN401 - raw PostgREST JSON row
    return Notification.model_validate(row)


class NotificationRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def unread_count(self, user_id: UUID) -> int:
        """Runs on every page load for the sidebar badge — must never scan
        more than the indexed (user_id, read_at, created_at) prefix.
        """

        def _do() -> int:
            resp = (
                self._client.table(_TABLE)
                .select("id", count=cast(Any, "exact"))
                .eq("user_id", str(user_id))
                .is_("read_at", "null")
                .execute()
            )
            return resp.count or 0

        return translate_errors(_do)

    def list_for_user(
        self, user_id: UUID, *, limit: int = 25, offset: int = 0
    ) -> Page[Notification]:
        limit = clamp_limit(limit)

        def _do() -> Page[Notification]:
            resp = (
                self._client.table(_TABLE)
                .select("*", count=cast(Any, "exact"))
                .eq("user_id", str(user_id))
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            items = tuple(_row_to_notification(row) for row in resp.data)
            total = resp.count if resp.count is not None else len(items)
            return Page[Notification](items=items, total=total, offset=offset, limit=limit)

        return translate_errors(_do)

    def mark_read(self, notification_id: UUID, *, user_id: UUID) -> None:
        """The only field this repository ever writes is read_at — see
        docs/DATA_SPEC.md #5.9. Scoped to user_id in the query as a second
        line of defense alongside RLS.
        """

        def _do() -> None:
            now = datetime.now(UTC).isoformat()
            self._client.table(_TABLE).update({"read_at": now}).eq("id", str(notification_id)).eq(
                "user_id", str(user_id)
            ).execute()

        translate_errors(_do)

    def mark_all_read(self, user_id: UUID) -> None:
        def _do() -> None:
            now = datetime.now(UTC).isoformat()
            self._client.table(_TABLE).update({"read_at": now}).eq("user_id", str(user_id)).is_(
                "read_at", "null"
            ).execute()

        translate_errors(_do)
