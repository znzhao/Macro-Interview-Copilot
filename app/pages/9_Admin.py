"""Admin page: review queue, bank management, bulk AI authoring, and basic
bank-health counts. Rendered only when profiles.is_admin is set
(streamlit_app.py navigation) — that is a UI convenience, not the
authorization boundary; RLS is (docs/DATA_SPEC.md #6.2). This page still
only ever reads/writes through RLS-scoped repository calls, and
ReviewRepository.approve/reject call is_admin()-checked SQL procedures, so a
non-admin who somehow reaches this page gets a PermissionDenied, not a write.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.state import get_auth_user, get_llm_api_key, get_llm_provider
from core.agent.authoring import AuthoringRequest, one_click_question_draft
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable, ConflictError, NotFound, PermissionDenied
from core.db.repositories.knowledge import KnowledgeRepository
from core.db.repositories.questions import QuestionRepository
from core.db.repositories.reviews import ReviewRepository
from core.llm.registry import DEFAULT_MODELS, get_provider
from core.models.enums import TOPICS_BY_MODULE, Difficulty, Module, QuestionTier, VerificationLevel
from core.models.knowledge import KnowledgeFilters
from core.models.question import QuestionDraft, QuestionFilters
from core.models.social import ContentKind

st.title("🛡️ Admin")

user = get_auth_user()
if user is None:
    st.error("You must be signed in.")
    st.stop()
user_id: UUID = user.id

client = get_client_as(user.access_token, user.refresh_token)
review_repo = ReviewRepository(client)
question_repo = QuestionRepository(client)
knowledge_repo = KnowledgeRepository(client)

review_tab, bank_tab, bulk_tab, health_tab = st.tabs(
    ["🕓 Review queue", "📚 Bank management", "🤖 Bulk authoring", "📊 Bank health"]
)

with review_tab:
    try:
        pending = review_repo.list_pending()
    except BackendUnavailable:
        st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
        pending = []

    if not pending:
        st.caption("Nothing pending review.")

    for req in pending:
        with st.container(border=True):
            title = "Question" if req.kind is ContentKind.QUESTION else "Knowledge document"
            try:
                if req.kind is ContentKind.QUESTION and req.question_id:
                    q = question_repo.get_or_raise(req.question_id)
                    st.markdown(f"**{q.question}**")
                    st.caption(f"`{q.module.value}` · `{q.topic}`")
                elif req.kind is ContentKind.KNOWLEDGE and req.doc_id:
                    doc = knowledge_repo.get_or_raise(req.doc_id)
                    st.markdown(f"**{doc.title}**")
                    st.caption(doc.summary)
            except NotFound:
                st.caption(f"{title} (no longer available)")

            if req.note:
                st.caption(f"Submitter note: {req.note}")

            approve_col, reject_col = st.columns(2)
            with approve_col:
                if st.button("Approve → verified", key=f"approve_{req.id}"):
                    try:
                        review_repo.approve(req.id)
                        st.success("Approved and promoted.")
                        st.rerun()
                    except (PermissionDenied, ConflictError, NotFound) as exc:
                        st.error(str(exc))
            with reject_col:
                note_key = f"reject_note_{req.id}"
                decision_note = st.text_input("Rejection reason (required)", key=note_key)
                if st.button("Reject", key=f"reject_{req.id}", disabled=not decision_note):
                    try:
                        review_repo.reject(req.id, decision_note=decision_note)
                        st.success("Rejected.")
                        st.rerun()
                    except (PermissionDenied, ConflictError, NotFound) as exc:
                        st.error(str(exc))

with bank_tab:
    kind_choice = st.radio(
        "Bank", ["Questions", "Knowledge"], horizontal=True, key="admin_bank_kind"
    )

    if kind_choice == "Questions":
        page = question_repo.search(
            filters=QuestionFilters(tiers=(QuestionTier.VERIFIED, QuestionTier.COMMUNITY)), limit=50
        )
        for q in page.items:
            with st.container(border=True):
                st.markdown(f"**{q.question}**")
                st.caption(f"`{q.tier.value}` · `{q.module.value}` · `{q.topic}`")
                cols = st.columns(2)
                with cols[0]:
                    if q.tier is not QuestionTier.VERIFIED and st.button(
                        "Promote directly", key=f"admin_promote_q_{q.id}"
                    ):
                        question_repo.set_tier(q.id, QuestionTier.VERIFIED.value)
                        st.rerun()
                with cols[1]:
                    if st.button("Archive", key=f"admin_archive_q_{q.id}"):
                        question_repo.set_status(q.id, "archived")
                        st.rerun()
    else:
        kpage = knowledge_repo.search(
            filters=KnowledgeFilters(tiers=(QuestionTier.VERIFIED, QuestionTier.COMMUNITY)),
            limit=50,
        )
        for doc in kpage.items:
            with st.container(border=True):
                st.markdown(f"**{doc.title}**")
                st.caption(f"`{doc.tier.value}`")
                if doc.tier is not QuestionTier.VERIFIED and st.button(
                    "Promote directly", key=f"admin_promote_k_{doc.id}"
                ):
                    knowledge_repo.set_tier(doc.id, QuestionTier.VERIFIED.value)
                    st.rerun()

with bulk_tab:
    st.caption(
        "Generate several verified questions directly, one call per question — no "
        "per-day cap enforcement yet (see PHASE_TRACKER.md Agent caveats), so keep "
        "batches small and review counts below."
    )
    api_key = get_llm_api_key()
    provider_name = get_llm_provider()
    if not api_key or not provider_name:
        st.warning("Add your LLM key in Settings to use bulk authoring.")
    else:
        module = st.selectbox("Module", options=list(Module), key="bulk_module")
        topic = st.selectbox("Topic", options=TOPICS_BY_MODULE[module], key="bulk_topic")
        difficulty = st.selectbox("Difficulty", options=list(Difficulty), key="bulk_difficulty")
        count = st.number_input("How many?", min_value=1, max_value=10, value=3)
        if st.button("Generate and add to verified bank"):
            provider = get_provider(provider_name, api_key)
            model = DEFAULT_MODELS[provider_name]
            created, failed = 0, 0
            for _ in range(int(count)):
                try:
                    request = AuthoringRequest(module=module, topic=topic, difficulty=difficulty)
                    schema_draft = one_click_question_draft(
                        provider=provider, model=model, request=request
                    )
                    question_repo.create(
                        QuestionDraft(
                            tier=QuestionTier.VERIFIED,
                            module=schema_draft.module,
                            topic=schema_draft.topic,
                            question=schema_draft.question,
                            difficulty=schema_draft.difficulty,
                            frequency=schema_draft.frequency,
                            target_roles=schema_draft.target_roles,
                            institutions=schema_draft.institutions,
                            verification_level=VerificationLevel.AI_GENERATED,
                            source_description=schema_draft.source_description,
                            source_url=schema_draft.source_url,
                            follow_up_questions=schema_draft.follow_up_questions,
                            answer_key=schema_draft.answer_key,
                        ),
                        author_id=user_id,
                    )
                    created += 1
                except Exception:  # noqa: BLE001 - one failure shouldn't stop the batch
                    failed += 1
            if created:
                st.success(f"Created {created} question(s).")
            if failed:
                st.warning(f"{failed} generation(s) failed and were skipped.")

with health_tab:
    verified_q = question_repo.search(
        filters=QuestionFilters(tiers=(QuestionTier.VERIFIED,)), limit=1
    )
    community_q = question_repo.search(
        filters=QuestionFilters(tiers=(QuestionTier.COMMUNITY,)), limit=1
    )
    verified_k = knowledge_repo.search(
        filters=KnowledgeFilters(tiers=(QuestionTier.VERIFIED,)), limit=1
    )
    community_k = knowledge_repo.search(
        filters=KnowledgeFilters(tiers=(QuestionTier.COMMUNITY,)), limit=1
    )
    pending_count = len(review_repo.list_pending())

    cols = st.columns(5)
    cols[0].metric("Verified questions", verified_q.total)
    cols[1].metric("Community questions", community_q.total)
    cols[2].metric("Verified docs", verified_k.total)
    cols[3].metric("Community docs", community_k.total)
    cols[4].metric("Pending reviews", pending_count)
