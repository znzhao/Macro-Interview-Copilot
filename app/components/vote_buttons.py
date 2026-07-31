"""Up/down vote widget, shared by questions and knowledge docs. See
docs/UI_SPEC.md #2, docs/DATA_SPEC.md #5.2 — dislikes never hide content,
they only sort and inform admin triage.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from core.db.repositories.votes import VoteRepository
from core.models.social import ContentKind


def vote_buttons(
    *,
    kind: ContentKind,
    target_id: UUID,
    user_id: UUID,
    upvotes: int,
    downvotes: int,
    vote_repo: VoteRepository,
    key_prefix: str,
) -> None:
    getter = (
        vote_repo.get_question_vote
        if kind is ContentKind.QUESTION
        else vote_repo.get_knowledge_vote
    )
    setter = (
        vote_repo.set_question_vote
        if kind is ContentKind.QUESTION
        else vote_repo.set_knowledge_vote
    )
    clearer = (
        vote_repo.clear_question_vote
        if kind is ContentKind.QUESTION
        else vote_repo.clear_knowledge_vote
    )
    current = getter(target_id, user_id)

    up_col, down_col = st.columns(2)
    with up_col:
        up_label = f"{'▲' if current == 1 else '△'} {upvotes}"
        if st.button(up_label, key=f"{key_prefix}_up", use_container_width=True):
            clearer(target_id, user_id) if current == 1 else setter(target_id, user_id, 1)
            st.rerun()
    with down_col:
        down_label = f"{'▼' if current == -1 else '▽'} {downvotes}"
        if st.button(down_label, key=f"{key_prefix}_down", use_container_width=True):
            clearer(target_id, user_id) if current == -1 else setter(target_id, user_id, -1)
            st.rerun()
