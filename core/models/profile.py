"""Profile, notes, and favorites domain models. See docs/DATA_SPEC.md #2, #5.4."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.models.enums import ExperienceLevel, TargetRole


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    display_name: str | None = None
    target_roles: tuple[TargetRole, ...] = ()
    experience_level: ExperienceLevel = ExperienceLevel.INTERMEDIATE
    preferred_provider: str | None = None
    preferred_model: str | None = None
    is_admin: bool = False
    created_at: datetime
    updated_at: datetime


class ProfilePatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    display_name: str | None = None
    target_roles: tuple[TargetRole, ...] | None = None
    experience_level: ExperienceLevel | None = None
    preferred_provider: str | None = None
    preferred_model: str | None = None


class Note(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    question_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime


class Favorite(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    question_id: UUID
    created_at: datetime
