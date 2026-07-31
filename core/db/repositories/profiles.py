"""Profile repository. See docs/DATA_SPEC.md #2, #8."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.db.errors import NotFound
from core.db.repositories.base import translate_errors
from core.models.profile import Profile, ProfilePatch

if TYPE_CHECKING:
    from supabase import Client

_TABLE = "profiles"


class ProfileRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self, user_id: UUID) -> Profile | None:
        def _do() -> Profile | None:
            resp = (
                self._client.table(_TABLE)
                .select("*")
                .eq("id", str(user_id))
                .maybe_single()
                .execute()
            )
            if resp is None or resp.data is None:
                return None
            return Profile.model_validate(resp.data)

        return translate_errors(_do)

    def get_or_raise(self, user_id: UUID) -> Profile:
        profile = self.get(user_id)
        if profile is None:
            raise NotFound(f"profile {user_id} not found")
        return profile

    def update(self, user_id: UUID, patch: ProfilePatch) -> Profile:
        def _do() -> Profile:
            payload = patch.model_dump(mode="json", exclude_none=True)
            resp = self._client.table(_TABLE).update(payload).eq("id", str(user_id)).execute()
            if not resp.data:
                raise NotFound(f"profile {user_id} not found")
            return Profile.model_validate(resp.data[0])

        return translate_errors(_do)
