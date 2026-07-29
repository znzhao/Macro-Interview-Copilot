"""Shared filter sidebar. Emits a typed QuestionFilters and syncs to the URL
query string so a filtered view is shareable and survives a rerun.
See docs/UI_SPEC.md #2, #3.8.
"""

from __future__ import annotations

import streamlit as st

from core.models.enums import Difficulty, Module, QuestionTier, VerificationLevel
from core.models.question import QuestionFilters


def _qp_list(name: str) -> list[str]:
    raw = st.query_params.get_all(name)
    return [v for v in raw if v]


def render_filter_sidebar() -> QuestionFilters:
    with st.sidebar:
        st.subheader("Filters")

        tiers = st.multiselect(
            "Tier",
            options=[t.value for t in QuestionTier],
            default=_qp_list("tier") or [QuestionTier.VERIFIED.value, QuestionTier.COMMUNITY.value],
        )
        modules = st.multiselect(
            "Module",
            options=[m.value for m in Module],
            default=_qp_list("module"),
        )
        difficulties = st.multiselect(
            "Difficulty",
            options=[d.value for d in Difficulty],
            default=_qp_list("difficulty"),
        )
        verification_levels = st.multiselect(
            "Verification level",
            options=[v.value for v in VerificationLevel],
            default=_qp_list("verification"),
        )
        favorited_only = st.checkbox("Favorites only", value=st.query_params.get("fav") == "1")

    st.query_params["tier"] = tiers
    st.query_params["module"] = modules
    st.query_params["difficulty"] = difficulties
    st.query_params["verification"] = verification_levels
    st.query_params["fav"] = "1" if favorited_only else "0"

    return QuestionFilters(
        tiers=tuple(QuestionTier(t) for t in tiers),
        modules=tuple(Module(m) for m in modules),
        difficulties=tuple(Difficulty(d) for d in difficulties),
        verification_levels=tuple(VerificationLevel(v) for v in verification_levels),
        favorited_only=favorited_only,
    )
