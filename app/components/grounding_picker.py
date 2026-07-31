"""Explicit knowledge-document picker for the authoring agent — the user
picks documents by hand and their full text is injected verbatim (the
"explicit picker, inject full text" decision). See docs/AI_SPEC.md #7,
docs/UI_SPEC.md #1.2c (the budget meter).
"""

from __future__ import annotations

import streamlit as st

from core.agent.limits import DEFAULT_CAPS
from core.db.repositories.knowledge import KnowledgeRepository
from core.models.enums import QuestionTier
from core.models.knowledge import KnowledgeDoc, KnowledgeFilters


def grounding_picker(
    *, knowledge_repo: KnowledgeRepository, key_prefix: str
) -> tuple[KnowledgeDoc, ...]:
    query = st.text_input("Search the knowledge bank", key=f"{key_prefix}_query")
    filters = KnowledgeFilters(tiers=(QuestionTier.VERIFIED, QuestionTier.COMMUNITY))
    page = knowledge_repo.search(query or None, filters=filters, limit=25)

    options = {f"{doc.title} ({doc.slug})": doc for doc in page.items}
    selected_labels = st.multiselect(
        "Ground the draft in these documents (optional)",
        options=list(options.keys()),
        key=f"{key_prefix}_select",
    )
    selected = tuple(options[label] for label in selected_labels)

    total_tokens = sum(d.token_estimate for d in selected)
    cap = DEFAULT_CAPS.max_grounding_tokens
    if total_tokens > cap:
        st.error(
            f"Selected documents use ~{total_tokens} tokens, over the {cap}-token budget. "
            "Deselect one."
        )
    else:
        st.caption(f"Grounding budget: ~{total_tokens} / {cap} tokens")

    return selected
