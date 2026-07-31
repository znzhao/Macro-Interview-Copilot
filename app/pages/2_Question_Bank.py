"""Question Bank page: tier tabs, search, filter, favorite, vote, comment,
share, and submit-for-review. See docs/UI_SPEC.md #1.2.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.components.answer_key_view import answer_key_view
from app.components.comment_thread import comment_thread
from app.components.confirm_dialog import confirm_action
from app.components.empty_states import no_search_results
from app.components.filters import render_filter_sidebar
from app.components.question_card import question_card
from app.components.vote_buttons import vote_buttons
from app.state import get_auth_user
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable, ConflictError
from core.db.repositories.comments import CommentRepository
from core.db.repositories.favorites import FavoriteRepository
from core.db.repositories.notes import NoteRepository
from core.db.repositories.questions import QuestionRepository
from core.db.repositories.reviews import ReviewRepository
from core.db.repositories.votes import VoteRepository
from core.models.enums import QuestionTier
from core.models.social import ContentKind, ReviewRequestDraft

st.title("📚 Question Bank")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view the Question Bank.")
    st.stop()
assert user is not None  # st.stop() above is NoReturn at runtime; unknown to mypy
user_id: UUID = user.id

client = get_client_as(user.access_token, user.refresh_token)
question_repo = QuestionRepository(client)
favorite_repo = FavoriteRepository(client)
note_repo = NoteRepository(client)
comment_repo = CommentRepository(client)
vote_repo = VoteRepository(client)
review_repo = ReviewRepository(client)

query = st.text_input("Search questions", placeholder="e.g. inflation, yield curve, China")
filters = render_filter_sidebar()

if "page_offset" not in st.session_state:
    st.session_state["page_offset"] = 0

try:
    favorites = {f.question_id for f in favorite_repo.list_for_user(user_id)}
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

if filters.favorited_only:
    # QuestionRepository.search doesn't special-case favorited_only (it needs the
    # caller's favorite set, which the repository layer intentionally doesn't know
    # about); filter client-side on this bounded page instead.
    pass

try:
    page = question_repo.search(
        query or None,
        filters=filters,
        limit=20,
        offset=st.session_state["page_offset"],
    )
except BackendUnavailable:
    st.error("Could not reach the database. Please retry in a moment.")
    st.stop()

items = page.items
if filters.favorited_only:
    items = tuple(q for q in items if q.id in favorites)

if not items:
    no_search_results(query)
else:
    for q in items:
        is_fav = q.id in favorites

        def _toggle_favorite(
            question_id: UUID = q.id,
            currently_favorited: bool = is_fav,
            current_user_id: UUID = user_id,
        ) -> None:
            if currently_favorited:
                favorite_repo.remove(current_user_id, question_id)
            else:
                favorite_repo.add(current_user_id, question_id)
            st.rerun()

        question_card(q, is_favorited=is_fav, on_favorite_toggle=_toggle_favorite)

        with st.expander("Answer key"):
            answer_key_view(q.answer_key)

        with st.expander("Notes"):
            existing = note_repo.get_for_question(user_id, q.id)
            note_text = st.text_area(
                "Your notes",
                value=existing.content if existing else "",
                key=f"note_{q.id}",
                label_visibility="collapsed",
            )
            if st.button("Save note", key=f"save_note_{q.id}"):
                note_repo.upsert(user_id, q.id, note_text)
                st.success("Saved.", icon="✅")

        if q.tier is not QuestionTier.PRIVATE:
            with st.expander("Votes and comments"):
                vote_buttons(
                    kind=ContentKind.QUESTION,
                    target_id=q.id,
                    user_id=user_id,
                    upvotes=q.upvotes,
                    downvotes=q.downvotes,
                    vote_repo=vote_repo,
                    key_prefix=f"q_{q.id}",
                )
                st.divider()
                comment_thread(
                    kind=ContentKind.QUESTION,
                    target_id=q.id,
                    user_id=user_id,
                    comment_repo=comment_repo,
                    key_prefix=f"q_{q.id}",
                )

        if q.owner_id == user_id and q.tier is QuestionTier.PRIVATE:
            with st.expander("Share"):
                if st.button("Share with community", key=f"share_{q.id}"):
                    question_repo.set_tier(q.id, QuestionTier.COMMUNITY.value)
                    st.rerun()

        if q.author_id == user_id and q.tier is QuestionTier.COMMUNITY:
            with st.expander("Submit for review"):
                if confirm_action(
                    message=(
                        "Submitting for review is permanent — the admin will always be able "
                        "to see this submission, even if you later change or remove the "
                        "question. Your original stays in the community bank either way."
                    ),
                    confirm_label="Submit for review",
                    key_prefix=f"submit_{q.id}",
                ):
                    try:
                        review_repo.submit(
                            ReviewRequestDraft(kind=ContentKind.QUESTION, question_id=q.id),
                            requester_id=user_id,
                        )
                        st.success("Submitted for review.")
                        st.rerun()
                    except ConflictError:
                        st.info("This question already has a pending review request.")

col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if st.session_state["page_offset"] > 0 and st.button("← Previous"):
        st.session_state["page_offset"] = max(0, st.session_state["page_offset"] - 20)
        st.rerun()
with col2:
    st.caption(f"{page.total} question(s) total")
with col3:
    if page.has_more and st.button("Next →"):
        st.session_state["page_offset"] += 20
        st.rerun()
