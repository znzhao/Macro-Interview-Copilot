"""Onboarding and zero-data states. First-class component, not an afterthought
— see docs/UI_SPEC.md #2.
"""

from __future__ import annotations

import streamlit as st


def onboarding_dashboard() -> None:
    st.info(
        "**Welcome — let's get you set up.**\n\n"
        "1. Set your target roles in [Settings](/Settings)\n"
        "2. Add your own LLM API key in Settings to unlock mock interviews\n"
        "3. Browse the [Question Bank](/Question_Bank) and start practicing\n\n"
        "Your progress, notes, and favorites show up here once you get going.",
        icon="👋",
    )


def no_search_results(query: str | None) -> None:
    if query:
        st.info(f"No questions matched **{query}**. Try a broader search or fewer filters.")
    else:
        st.info("No questions match the current filters. Try widening them.")


def no_llm_key_banner() -> None:
    st.warning(
        "No LLM API key is set for this session, so mock interviews and AI-assisted "
        "authoring are unavailable. Add your own key in Settings — browsing, notes, "
        "and favorites work fully without one.",
        icon="🔑",
    )
