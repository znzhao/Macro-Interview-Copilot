"""Knowledge bank page: search, tier tabs, votes, comments, and the
private/community share toggle. Mirrors 2_Question_Bank.py — D12 governs both
banks alike. See docs/UI_SPEC.md.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.components.answer_key_view import (
    answer_key_view,  # noqa: F401 - kept for symmetry; unused here
)
from app.components.comment_thread import comment_thread
from app.components.confirm_dialog import confirm_action
from app.components.knowledge_card import knowledge_card
from app.components.vote_buttons import vote_buttons
from app.state import get_auth_user
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable, ConflictError
from core.db.repositories.comments import CommentRepository
from core.db.repositories.knowledge import KnowledgeRepository
from core.db.repositories.reviews import ReviewRepository
from core.db.repositories.votes import VoteRepository
from core.models.enums import QuestionTier
from core.models.knowledge import KnowledgeFilters
from core.models.social import ContentKind, ReviewRequestDraft

st.title("📖 Knowledge Bank")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view the Knowledge Bank.")
    st.stop()
user_id: UUID = user.id

client = get_client_as(user.access_token, user.refresh_token)
knowledge_repo = KnowledgeRepository(client)
comment_repo = CommentRepository(client)
vote_repo = VoteRepository(client)
review_repo = ReviewRepository(client)

tier_tab, community_tab, mine_tab = st.tabs(["✅ Verified", "🌐 Community", "🔒 My documents"])

query = st.session_state.get("knowledge_query", "")


def _render_open_doc(doc_id: UUID) -> None:
    doc = knowledge_repo.get_or_raise(doc_id)
    st.subheader(doc.title)
    st.caption(doc.summary)
    st.markdown(doc.body_md)

    if doc.tier is not QuestionTier.PRIVATE:
        vote_buttons(
            kind=ContentKind.KNOWLEDGE,
            target_id=doc.id,
            user_id=user_id,
            upvotes=doc.upvotes,
            downvotes=doc.downvotes,
            vote_repo=vote_repo,
            key_prefix=f"kdoc_{doc.id}",
        )
        st.divider()
        comment_thread(
            kind=ContentKind.KNOWLEDGE,
            target_id=doc.id,
            user_id=user_id,
            comment_repo=comment_repo,
            key_prefix=f"kdoc_{doc.id}",
        )

    if doc.owner_id == user_id and doc.tier is QuestionTier.PRIVATE:
        st.divider()
        if st.button("Share with community", key=f"share_{doc.id}"):
            knowledge_repo.set_tier(doc.id, QuestionTier.COMMUNITY.value)
            st.rerun()

    if doc.author_id == user_id and doc.tier is QuestionTier.COMMUNITY:
        st.divider()
        st.markdown("**Submit to the admin for review**")
        if confirm_action(
            message=(
                "Submitting for review is permanent — the admin will always be able to see "
                "this submission, even if you later change or remove the document. Your "
                "original stays in the community bank either way."
            ),
            confirm_label="Submit for review",
            key_prefix=f"submit_{doc.id}",
        ):
            try:
                review_repo.submit(
                    ReviewRequestDraft(kind=ContentKind.KNOWLEDGE, doc_id=doc.id),
                    requester_id=user_id,
                )
                st.success("Submitted for review.")
                st.rerun()
            except ConflictError:
                st.info("This document already has a pending review request.")


try:
    with tier_tab:
        q = st.text_input("Search verified knowledge", key="knowledge_query_verified")
        page = knowledge_repo.search(
            q or None, filters=KnowledgeFilters(tiers=(QuestionTier.VERIFIED,)), limit=25
        )
        if not page.items:
            st.caption("No verified documents yet.")
        for doc in page.items:
            knowledge_card(
                doc, on_open=lambda d=doc: st.session_state.__setitem__("open_doc", d.id)
            )

    with community_tab:
        q2 = st.text_input("Search community knowledge", key="knowledge_query_community")
        page2 = knowledge_repo.search(
            q2 or None, filters=KnowledgeFilters(tiers=(QuestionTier.COMMUNITY,)), limit=25
        )
        if not page2.items:
            st.caption("No community documents yet.")
        for doc in page2.items:
            knowledge_card(
                doc, on_open=lambda d=doc: st.session_state.__setitem__("open_doc", d.id)
            )

    with mine_tab:
        q3 = st.text_input("Search my documents", key="knowledge_query_mine")
        page3 = knowledge_repo.search(
            q3 or None, filters=KnowledgeFilters(tiers=(QuestionTier.PRIVATE,)), limit=25
        )
        if not page3.items:
            st.caption("No private documents yet. Upload or generate one from the Author page.")
        for doc in page3.items:
            if doc.owner_id != user_id:
                continue
            knowledge_card(
                doc, on_open=lambda d=doc: st.session_state.__setitem__("open_doc", d.id)
            )
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

open_doc_id = st.session_state.get("open_doc")
if open_doc_id:
    st.divider()
    if st.button("← Close"):
        st.session_state.pop("open_doc", None)
        st.rerun()
    _render_open_doc(open_doc_id)
