"""Render and edit an AnswerKey. Structured bullets only — see D10 and
core/models/answer_key.py. This is the only place that renders an answer key
in the UI, so the "bullets, never prose" shape looks the same everywhere.
"""

from __future__ import annotations

import streamlit as st

from core.models.answer_key import AnswerKey

_SECTION_LABELS: dict[str, str] = {
    "framework": "Framework",
    "mechanism": "Mechanism",
    "indicators": "Indicators to cite",
    "market_implication": "Market implication",
    "common_traps": "Common traps",
}


def answer_key_view(key: AnswerKey) -> None:
    if key.is_empty:
        st.caption("No answer key yet.")
        return
    for field_name, label in _SECTION_LABELS.items():
        bullets = getattr(key, field_name)
        if not bullets:
            continue
        st.markdown(f"**{label}**")
        for bullet in bullets:
            st.markdown(f"- {bullet}")


def answer_key_editor(key: AnswerKey, *, key_prefix: str) -> AnswerKey:
    """Renders one text area per section (one bullet per line) and returns
    the edited AnswerKey. Pydantic re-validates the result — an over-long
    line or a ninth bullet fails the same way a bad AI draft would.
    """
    sections: dict[str, tuple[str, ...]] = {}
    for field_name, label in _SECTION_LABELS.items():
        existing = "\n".join(getattr(key, field_name))
        raw = st.text_area(
            f"{label} (one bullet per line)", value=existing, key=f"{key_prefix}_{field_name}"
        )
        sections[field_name] = tuple(line.strip() for line in raw.splitlines() if line.strip())
    return AnswerKey(**sections)
