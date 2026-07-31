"""Review request repository. See docs/DATA_SPEC.md #5.7, #8.3 and
docs/DECISIONS.md D14.

Approval and rejection call the SECURITY DEFINER Postgres functions in
core/db/migrations/0005_phase2_rls.sql (approve_review_request /
reject_review_request) via RPC, never three separate client writes — clone,
decision, and notification must commit as one transaction, and only the
database can guarantee that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from core.db.errors import ConflictError, NotFound, PermissionDenied
from core.db.repositories.base import translate_errors
from core.models.social import ReviewRequest, ReviewRequestDraft

T = TypeVar("T")

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "review_requests"


def _row_to_request(row: Any) -> ReviewRequest:  # noqa: ANN401 - raw PostgREST JSON row
    return ReviewRequest.model_validate(row)


class ReviewRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self, request_id: UUID) -> ReviewRequest | None:
        def _do() -> ReviewRequest | None:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("id", str(request_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return _row_to_request(resp.data)

        return translate_errors(_do)

    def list_for_user(self, requester_id: UUID) -> list[ReviewRequest]:
        """My Drafts' submission-status view — see docs/UI_SPEC.md #1.2d."""

        def _do() -> list[ReviewRequest]:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("requester_id", str(requester_id))
                .order("created_at", desc=True)
                .execute()
            )
            return [_row_to_request(row) for row in resp.data]

        return translate_errors(_do)

    def list_pending(self) -> list[ReviewRequest]:
        """Admin-only in practice — RLS restricts SELECT to the requester or
        an admin, so a non-admin caller simply gets their own pending rows.
        """

        def _do() -> list[ReviewRequest]:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("status", "pending")
                .order("created_at")
                .execute()
            )
            return [_row_to_request(row) for row in resp.data]

        return translate_errors(_do)

    def submit(self, draft: ReviewRequestDraft, *, requester_id: UUID) -> ReviewRequest:
        """Raises ConflictError if this content already has a pending request
        — the partial unique indexes in 0004 enforce "only one at a time".
        """

        def _do() -> ReviewRequest:
            payload = draft.model_dump(mode="json", exclude_none=True)
            payload["requester_id"] = str(requester_id)
            resp = self._client.table(_TABLE).insert(payload).execute()
            return _row_to_request(cast(dict[str, Any], resp.data[0]))

        return translate_errors(_do)

    def approve(self, request_id: UUID, *, decision_note: str | None = None) -> UUID:
        """Returns the id of the newly created verified clone.

        Raises PermissionDenied if the caller is not an admin (the function
        itself checks is_admin() and raises), NotFound if the request does
        not exist, or ConflictError if it is not pending.
        """

        def _do() -> UUID:
            resp = self._client.rpc(
                "approve_review_request",
                {"p_request_id": str(request_id), "p_decision_note": decision_note},
            ).execute()
            return UUID(cast(str, resp.data))

        return _translate_rpc_errors(_do, request_id)

    def reject(self, request_id: UUID, *, decision_note: str) -> None:
        """decision_note is required — shown to the author, and the Postgres
        function itself rejects an empty one.
        """

        def _do() -> None:
            self._client.rpc(
                "reject_review_request",
                {"p_request_id": str(request_id), "p_decision_note": decision_note},
            ).execute()

        _translate_rpc_errors(_do, request_id)


def _translate_rpc_errors(fn: Callable[[], T], request_id: UUID) -> T:  # noqa: UP047 - py3.11 dev env compat
    """RPC calls to plpgsql RAISE EXCEPTION surface as generic postgrest
    errors whose message text is the only signal available — translate the
    specific messages the two functions raise into the same typed errors the
    rest of the repository layer uses, per docs/DATA_SPEC.md #8.2.
    """
    try:
        return translate_errors(fn)
    except Exception as exc:  # noqa: BLE001 - re-typed below, not swallowed
        message = str(exc).lower()
        if "only an admin" in message:
            raise PermissionDenied(str(exc)) from exc
        if "not found" in message:
            raise NotFound(f"review request {request_id} not found") from exc
        if "not pending" in message or "decision note is required" in message:
            raise ConflictError(str(exc)) from exc
        raise
