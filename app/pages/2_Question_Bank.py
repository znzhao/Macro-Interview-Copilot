"""Question Bank page: search, filter, favorite, and annotate questions.
See docs/UI_SPEC.md #1.2.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.components.empty_states import no_search_results
from app.components.filters import render_filter_sidebar
from app.components.question_card import question_card
from app.state import get_auth_user
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable
from core.db.repositories.favorites import FavoriteRepository
from core.db.repositories.notes import NoteRepository
from core.db.repositories.questions import QuestionRepository

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
