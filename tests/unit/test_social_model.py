"""Unit tests for core.models.social: comments, review requests, notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.models.social import (
    Comment,
    ContentKind,
    Notification,
    NotificationKind,
    ReviewRequest,
    ReviewStatus,
)


def test_comment_display_body_hides_tombstoned_text() -> None:
    comment = Comment(
        id=uuid4(),
        kind=ContentKind.QUESTION,
        question_id=uuid4(),
        author_id=uuid4(),
        body="the original text",
        is_deleted=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    # display_body is what the UI must render — never `body` directly, or a
    # tombstoned comment's original text leaks through a raw-field read.
    assert comment.display_body == "[removed]"
    assert comment.body == "the original text"


def test_comment_display_body_shows_live_text() -> None:
    comment = Comment(
        id=uuid4(),
        kind=ContentKind.KNOWLEDGE,
        doc_id=uuid4(),
        author_id=uuid4(),
        body="a real comment",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert comment.display_body == "a real comment"


def test_comment_body_length_bounds() -> None:
    with pytest.raises(ValidationError):
        Comment(
            id=uuid4(),
            kind=ContentKind.QUESTION,
            question_id=uuid4(),
            author_id=uuid4(),
            body="x" * 4001,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_review_request_defaults_to_pending() -> None:
    req = ReviewRequest(
        id=uuid4(),
        kind=ContentKind.QUESTION,
        question_id=uuid4(),
        requester_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    assert req.status is ReviewStatus.PENDING
    assert req.decided_at is None


def test_notification_is_unread_until_read_at_is_set() -> None:
    notif = Notification(
        id=uuid4(),
        user_id=uuid4(),
        kind=NotificationKind.SUBMISSION_APPROVED,
        title="Your question was promoted",
        created_at=datetime.now(UTC),
    )
    assert notif.is_unread

    read_notif = notif.model_copy(update={"read_at": datetime.now(UTC)})
    assert not read_notif.is_unread
