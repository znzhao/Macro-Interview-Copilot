"""Interview session and turn domain models. See docs/DATA_SPEC.md #4, docs/AI_SPEC.md #4."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.models.enums import InterviewerMode, Module, SessionStatus


class SessionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    planned_turns: int = Field(default=5, ge=1, le=20)
    difficulty_target: str | None = None
    modules: tuple[Module, ...] = ()
    adaptive: bool = False
    seed: int | None = None


class InterviewSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    mode: InterviewerMode
    institution: str | None = None
    config: SessionConfig
    status: SessionStatus
    overall_score: int | None = Field(default=None, ge=0, le=100)
    started_at: datetime
    ended_at: datetime | None = None


class InterviewTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    session_id: UUID
    ordinal: int = Field(ge=1)
    question_id: UUID | None = None
    question_text: str = Field(min_length=1)
    is_followup: bool = False
    parent_turn_id: UUID | None = None
    answer_text: str | None = None
    answer_seconds: int | None = Field(default=None, ge=0)
    created_at: datetime
    answered_at: datetime | None = None
