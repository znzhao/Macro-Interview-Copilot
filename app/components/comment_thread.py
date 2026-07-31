"""One-level comment thread, shared by questions and knowledge docs. See
docs/UI_SPEC.md #2, docs/DATA_SPEC.md #5.8 — replies-to-replies are rejected
by the database, so this component never offers a reply button on a reply.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from core.db.repositories.comments import CommentRepository
from core.models.social import Comment, CommentDraft, ContentKind


def comment_thread(
    *,
    kind: ContentKind,
    target_id: UUID,
    user_id: UUID,
    comment_repo: CommentRepository,
    key_prefix: str,
) -> None:
    comments = comment_repo.list_for_target(kind, target_id)
    top_level = [c for c in comments if c.parent_id is None]
    replies_by_parent: dict[UUID, list[Comment]] = {}
    for c in comments:
        if c.parent_id is not None:
            replies_by_parent.setdefault(c.parent_id, []).append(c)

    if not top_level:
        st.caption("No comments yet.")

    for comment in top_level:
        st.markdown(f"**{'—' if comment.is_deleted else 'User'}:** {comment.display_body}")
        for reply in replies_by_parent.get(comment.id, []):
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ {reply.display_body}", unsafe_allow_html=True)

        if not comment.is_deleted:
            with st.expander("Reply", expanded=False):
                reply_text = st.text_area(
                    "Reply", key=f"{key_prefix}_reply_{comment.id}", label_visibility="collapsed"
                )
                if (
                    st.button("Post reply", key=f"{key_prefix}_reply_btn_{comment.id}")
                    and reply_text
                ):
                    draft = CommentDraft(
                        kind=kind,
                        question_id=target_id if kind is ContentKind.QUESTION else None,
                        doc_id=target_id if kind is ContentKind.KNOWLEDGE else None,
                        parent_id=comment.id,
                        body=reply_text,
                    )
                    comment_repo.post(draft, author_id=user_id)
                    st.rerun()

        if (
            comment.author_id == user_id
            and not comment.is_deleted
            and st.button("Delete", key=f"{key_prefix}_del_{comment.id}")
        ):
            comment_repo.tombstone(comment.id)
            st.rerun()

    st.divider()
    new_text = st.text_area("Add a comment", key=f"{key_prefix}_new")
    if st.button("Post comment", key=f"{key_prefix}_post") and new_text:
        draft = CommentDraft(
            kind=kind,
            question_id=target_id if kind is ContentKind.QUESTION else None,
            doc_id=target_id if kind is ContentKind.KNOWLEDGE else None,
            body=new_text,
        )
        comment_repo.post(draft, author_id=user_id)
        st.rerun()
