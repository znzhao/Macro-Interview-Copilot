"""Comments, review requests, notifications, and votes. See docs/DATA_SPEC.md
#5.2, #5.7, #5.8, #5.9 and docs/DECISIONS.md D14, D15.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContentKind(StrEnum):
    QUESTION = "question"
    KNOWLEDGE = "knowledge"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class NotificationKind(StrEnum):
    SUBMISSION_APPROVED = "submission_approved"
    SUBMISSION_REJECTED = "submission_rejected"
    COMMENT_ON_CONTENT = "comment_on_content"
    REPLY_TO_COMMENT = "reply_to_comment"


# ── Votes ────────────────────────────────────────────────────────────────
# ±1 only. Dislikes never hide anything — they sort and inform admin triage;
# hiding is question_reports' job alone. See docs/DATA_SPEC.md #5.2.
VoteValue = Literal[-1, 1]


class Vote(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    target_id: UUID
    value: VoteValue
    created_at: datetime
    updated_at: datetime


# ── Comments ─────────────────────────────────────────────────────────────
class Comment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: ContentKind
    question_id: UUID | None = None
    doc_id: UUID | None = None
    parent_id: UUID | None = None
    author_id: UUID | None = None
    body: str = Field(min_length=1, max_length=4000)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    @property
    def display_body(self) -> str:
        """The UI renders this, never `body` directly, so a tombstoned
        comment never leaks its original text through a raw-field read.
        """
        return "[removed]" if self.is_deleted else self.body


class CommentDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ContentKind
    question_id: UUID | None = None
    doc_id: UUID | None = None
    parent_id: UUID | None = None
    body: str = Field(min_length=1, max_length=4000)


# ── Review requests ──────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: ContentKind
    question_id: UUID | None = None
    doc_id: UUID | None = None
    requester_id: UUID
    note: str | None = None
    status: ReviewStatus = ReviewStatus.PENDING
    decided_by: UUID | None = None
    decision_note: str | None = None
    promoted_id: UUID | None = None
    created_at: datetime
    decided_at: datetime | None = None


class ReviewRequestDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ContentKind
    question_id: UUID | None = None
    doc_id: UUID | None = None
    note: str | None = None


# ── Notifications ────────────────────────────────────────────────────────
class Notification(BaseModel):
    """Trigger-written only — see docs/DECISIONS.md D15. There is no
    NotificationDraft: the repository layer never inserts one.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    user_id: UUID
    kind: NotificationKind
    title: str
    body: str | None = None
    link_kind: ContentKind | None = None
    link_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime

    @property
    def is_unread(self) -> bool:
        return self.read_at is None
