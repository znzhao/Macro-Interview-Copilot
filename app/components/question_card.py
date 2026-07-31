"""Consistent question rendering everywhere — one card, one look, every page.
See docs/UI_SPEC.md #2 and #4 (the verification badge must never be hand-rolled
per page).
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.components.badges import verification_badge
from core.models.question import Question

__all__ = ["question_card", "question_id_from_key", "verification_badge"]


def question_card(
    question: Question,
    *,
    is_favorited: bool = False,
    on_favorite_toggle: object = None,
    on_practice: object = None,
) -> None:
    """Render one question card. `on_favorite_toggle` / `on_practice` are optional
    zero-arg callables; pass None to omit the corresponding button.
    """
    with st.container(border=True):
        top = st.columns([5, 1])
        with top[0]:
            st.markdown(f"**{question.question}**")
        with top[1]:
            verification_badge(question.verification_level.value)

        meta = (
            f"`{question.module.value}` · `{question.topic}` · {question.difficulty.value.title()}"
        )
        if question.institutions:
            meta += " · " + ", ".join(question.institutions[:3])
        st.caption(meta)

        if question.source_url:
            st.caption(f"Source: {question.source_url}")

        actions = st.columns(4)
        with actions[0]:
            if on_practice is not None and st.button(
                "Practice", key=f"practice_{question.id}", use_container_width=True
            ):
                on_practice()  # type: ignore[operator]
        with actions[1]:
            label = "★ Favorited" if is_favorited else "☆ Favorite"
            if on_favorite_toggle is not None and st.button(
                label, key=f"fav_{question.id}", use_container_width=True
            ):
                on_favorite_toggle()  # type: ignore[operator]
        with actions[2]:
            st.caption(f"👍 {question.upvotes}")
        with actions[3]:
            st.caption(question.ref)

        if question.follow_up_questions:
            with st.expander("Seed follow-up questions"):
                for fq in question.follow_up_questions:
                    st.markdown(f"- {fq}")


def question_id_from_key(key: str, prefix: str) -> UUID:
    return UUID(key.removeprefix(prefix))
