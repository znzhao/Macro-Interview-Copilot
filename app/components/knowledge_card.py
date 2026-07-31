"""Consistent knowledge document rendering everywhere — mirrors question_card.py,
since D12 governs both banks alike. See docs/UI_SPEC.md #2, #4.
"""

from __future__ import annotations

import streamlit as st

from app.components.badges import tier_badge, verification_badge
from core.models.knowledge import KnowledgeDoc


def knowledge_card(doc: KnowledgeDoc, *, on_open: object = None) -> None:
    """`on_open` is an optional zero-arg callable; pass None to omit the button."""
    with st.container(border=True):
        top = st.columns([5, 1])
        with top[0]:
            st.markdown(f"**{doc.title}**")
        with top[1]:
            verification_badge(doc.verification_level.value)

        st.caption(doc.summary)

        meta_cols = st.columns([3, 1])
        with meta_cols[0]:
            if doc.modules:
                st.caption(" · ".join(f"`{m.value}`" for m in doc.modules))
        with meta_cols[1]:
            tier_badge(doc.tier.value)

        actions = st.columns(3)
        with actions[0]:
            if on_open is not None and st.button(
                "Open", key=f"open_{doc.id}", use_container_width=True
            ):
                on_open()  # type: ignore[operator]
        with actions[1]:
            st.caption(f"👍 {doc.upvotes} 👎 {doc.downvotes}")
        with actions[2]:
            st.caption(f"~{doc.token_estimate} tok")
