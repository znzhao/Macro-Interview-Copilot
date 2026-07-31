"""My Drafts: the submission-status view for review requests the current user
has made, for either bank. See docs/UI_SPEC.md #1.2d, docs/DECISIONS.md D14.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.state import get_auth_user
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable, NotFound
from core.db.repositories.knowledge import KnowledgeRepository
from core.db.repositories.questions import QuestionRepository
from core.db.repositories.reviews import ReviewRepository
from core.models.social import ContentKind, ReviewStatus

st.title("🗂️ My Drafts")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view My Drafts.")
    st.stop()
user_id: UUID = user.id

client = get_client_as(user.access_token, user.refresh_token)
review_repo = ReviewRepository(client)
question_repo = QuestionRepository(client)
knowledge_repo = KnowledgeRepository(client)

_STATUS_ICON = {
    ReviewStatus.PENDING: "🕓",
    ReviewStatus.APPROVED: "✅",
    ReviewStatus.REJECTED: "❌",
    ReviewStatus.WITHDRAWN: "↩️",
}

try:
    requests = review_repo.list_for_user(user_id)
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

if not requests:
    st.caption(
        "No review requests yet. Submit a question or knowledge document for review from "
        "the Question Bank or Knowledge pages."
    )

for req in requests:
    with st.container(border=True):
        icon = _STATUS_ICON.get(req.status, "•")
        title = "Question" if req.kind is ContentKind.QUESTION else "Knowledge document"

        label = title
        try:
            if req.kind is ContentKind.QUESTION and req.question_id:
                label = question_repo.get_or_raise(req.question_id).question
            elif req.kind is ContentKind.KNOWLEDGE and req.doc_id:
                label = knowledge_repo.get_or_raise(req.doc_id).title
        except (NotFound, BackendUnavailable):
            label = f"{title} (no longer available)"

        st.markdown(f"{icon} **{label}**")
        st.caption(f"{title} · Status: {req.status.value} · Submitted {req.created_at:%Y-%m-%d}")
        if req.decision_note:
            st.caption(f"Admin note: {req.decision_note}")
