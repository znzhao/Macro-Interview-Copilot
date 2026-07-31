"""Shared badges for both banks (questions and knowledge docs) — one
verification badge, one tier badge, never hand-rolled per page.
See docs/UI_SPEC.md #4.
"""

from __future__ import annotations

import streamlit as st

_VERIFICATION_LABELS: dict[str, tuple[str, str]] = {
    "verified_interview": ("🟢 Verified interview", "Reported from a real interview."),
    "multiple_independent_reports": (
        "🟢 Multiple reports",
        "Corroborated by more than one independent interview report.",
    ),
    "official_publication": (
        "🔵 Official publication",
        "Drawn from an official research publication.",
    ),
    "official_job_material": (
        "🔵 Official job material",
        "Drawn from official hiring materials.",
    ),
    "synthesized_from_official_topics": (
        "🟡 Synthesized",
        "Derived from official research topics — not a reported interview question.",
    ),
    "ai_generated": ("🟠 AI-generated", "Drafted by AI. Not yet source-verified."),
    "user_submitted": ("🟠 User-submitted", "Submitted by a community member."),
}

_TIER_LABELS: dict[str, str] = {
    "verified": "✅ Verified bank",
    "community": "🌐 Community",
    "private": "🔒 Private",
}


def verification_badge(level: str) -> None:
    label, tooltip = _VERIFICATION_LABELS.get(level, (level, ""))
    st.caption(label, help=tooltip or None)


def tier_badge(tier: str) -> None:
    st.caption(_TIER_LABELS.get(tier, tier))
