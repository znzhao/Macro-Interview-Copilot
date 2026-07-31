"""Author page: one-click and agentic-refinement authoring for both banks.
See docs/AI_SPEC.md #6, docs/UI_SPEC.md.

Session state on this page is scoped by a single dict under "author_state"
rather than many top-level keys, since the whole authoring session (kind,
transcript, usage, current draft) needs to reset together whenever the user
starts a new draft.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.components.answer_key_view import answer_key_editor, answer_key_view
from app.components.empty_states import no_llm_key_banner
from app.components.grounding_picker import grounding_picker
from app.state import get_auth_user, get_llm_api_key, get_llm_provider
from core.agent.authoring import (
    AuthoringRequest,
    continue_question_refinement,
    one_click_question_draft,
    start_question_refinement,
)
from core.agent.knowledge_authoring import (
    KnowledgeAuthoringRequest,
    continue_knowledge_refinement,
    one_click_knowledge_draft,
    start_knowledge_refinement,
)
from core.agent.tools.registry import ToolContext
from core.agent.tools.uploads import Upload, check_upload_count, parse_upload
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable
from core.db.repositories.knowledge import KnowledgeRepository
from core.db.repositories.questions import QuestionRepository
from core.llm.registry import DEFAULT_MODELS, get_provider
from core.llm.schemas import KnowledgeDraftSchema, QuestionDraftSchema
from core.models.enums import TOPICS_BY_MODULE, Difficulty, Module, QuestionTier, VerificationLevel
from core.models.knowledge import KnowledgeDraft
from core.models.question import QuestionDraft

st.title("✍️ Author")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to use the authoring agent.")
    st.stop()
user_id: UUID = user.id

api_key = get_llm_api_key()
provider_name = get_llm_provider()
if not api_key or not provider_name:
    no_llm_key_banner()
    st.stop()

client = get_client_as(user.access_token, user.refresh_token)
knowledge_repo = KnowledgeRepository(client)
question_repo = QuestionRepository(client)

if "author_state" not in st.session_state:
    st.session_state["author_state"] = {}
astate = st.session_state["author_state"]

content_type = st.radio(
    "What are you authoring?", ["Question", "Knowledge document"], horizontal=True
)

if astate.get("content_type") != content_type:
    st.session_state["author_state"] = {"content_type": content_type}
    astate = st.session_state["author_state"]

uploads: dict[str, Upload] = astate.setdefault("uploads", {})
uploaded_files = st.file_uploader(
    "Attach reference files (.md/.txt, up to 3, 1MB each — optional)",
    accept_multiple_files=True,
    key=f"uploads_{content_type}",
)
if uploaded_files:
    for f in uploaded_files:
        if f.name not in uploads:
            try:
                check_upload_count(len(uploads))
                uploads[f.name] = parse_upload(f.name, f.getvalue())
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(str(exc))

tool_context = ToolContext(knowledge_repo=knowledge_repo, uploads=uploads)
model = DEFAULT_MODELS[provider_name]

st.divider()

if content_type == "Question":
    module = st.selectbox("Module", options=list(Module))
    topic = st.selectbox("Topic", options=TOPICS_BY_MODULE[module])
    difficulty = st.selectbox("Difficulty", options=list(Difficulty))
    seed_context = st.text_area("Anything else the agent should know? (optional)")
    request = AuthoringRequest(
        module=module, topic=topic, difficulty=difficulty, seed_context=seed_context
    )

    one_click_col, refine_col = st.columns(2)
    with one_click_col:
        if st.button("⚡ Generate now (one click)", use_container_width=True):
            try:
                provider = get_provider(provider_name, api_key)
                draft = one_click_question_draft(provider=provider, model=model, request=request)
                astate["draft"] = draft
                astate["transcript"] = ()
                astate["note"] = None
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Generation failed: {exc}")
    with refine_col:
        grounding = grounding_picker(knowledge_repo=knowledge_repo, key_prefix="q_grounding")
        if st.button("💬 Start refinement conversation", use_container_width=True):
            try:
                provider = get_provider(provider_name, api_key)
                outcome = start_question_refinement(
                    provider=provider,
                    model=model,
                    request=request,
                    grounding_docs=grounding,
                    tool_context=tool_context,
                )
                astate["draft"] = outcome.draft
                astate["transcript"] = outcome.transcript
                astate["note"] = outcome.note
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Refinement failed: {exc}")

else:
    topic = st.text_input("Topic")
    material = st.text_area("Source material to draw on (optional)")
    krequest = KnowledgeAuthoringRequest(topic=topic, material=material)

    one_click_col, refine_col = st.columns(2)
    with one_click_col:
        if st.button("⚡ Generate now (one click)", use_container_width=True, disabled=not topic):
            try:
                provider = get_provider(provider_name, api_key)
                kdraft = one_click_knowledge_draft(provider=provider, model=model, request=krequest)
                astate["draft"] = kdraft
                astate["transcript"] = ()
                astate["note"] = None
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Generation failed: {exc}")
    with refine_col:
        grounding = grounding_picker(knowledge_repo=knowledge_repo, key_prefix="k_grounding")
        if st.button(
            "💬 Start refinement conversation", use_container_width=True, disabled=not topic
        ):
            try:
                provider = get_provider(provider_name, api_key)
                k_outcome = start_knowledge_refinement(
                    provider=provider,
                    model=model,
                    request=krequest,
                    grounding_docs=grounding,
                    tool_context=tool_context,
                )
                astate["draft"] = k_outcome.draft
                astate["transcript"] = k_outcome.transcript
                astate["note"] = k_outcome.note
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Refinement failed: {exc}")

st.divider()

draft = astate.get("draft")
note = astate.get("note")
if note:
    st.info(note)

if draft is None:
    st.caption("No draft yet — generate one above.")
    st.stop()

st.subheader("Draft")

if content_type == "Question" and isinstance(draft, QuestionDraftSchema):
    edited_question = st.text_area("Question text", value=draft.question, height=100)
    st.markdown("**Answer key**")
    edited_answer_key = answer_key_editor(draft.answer_key, key_prefix="edit_qak")

    feedback = st.text_area("Feedback for the next refinement turn (optional)")
    refine_col, save_col, discard_col = st.columns(3)
    with refine_col:
        if st.button("Refine with feedback", disabled=not feedback):
            edited = draft.model_copy(
                update={"question": edited_question, "answer_key": edited_answer_key}
            )
            try:
                provider = get_provider(provider_name, api_key)
                outcome = continue_question_refinement(
                    provider=provider,
                    model=model,
                    transcript=astate.get("transcript", ()),
                    feedback=feedback,
                    edited_draft=edited,
                    tool_context=tool_context,
                )
                astate["draft"] = outcome.draft or edited
                astate["transcript"] = outcome.transcript
                astate["note"] = outcome.note
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Refinement failed: {exc}")
    with save_col:
        if st.button("💾 Save to my private bank"):
            try:
                question_draft = QuestionDraft(
                    tier=QuestionTier.PRIVATE,
                    module=draft.module,
                    topic=draft.topic,
                    question=edited_question,
                    difficulty=draft.difficulty,
                    frequency=draft.frequency,
                    target_roles=draft.target_roles,
                    institutions=draft.institutions,
                    verification_level=VerificationLevel.AI_GENERATED,
                    source_description=draft.source_description,
                    source_url=draft.source_url,
                    follow_up_questions=draft.follow_up_questions,
                    answer_key=edited_answer_key,
                )
                question_repo.create(question_draft, author_id=user_id)
                st.success("Saved to your private bank.")
                st.session_state.pop("author_state", None)
                st.rerun()
            except BackendUnavailable:
                st.error("Could not reach the database. Please retry.")
    with discard_col:
        if st.button("Discard"):
            st.session_state.pop("author_state", None)
            st.rerun()

    with st.expander("Preview"):
        answer_key_view(edited_answer_key)

elif content_type == "Knowledge document" and isinstance(draft, KnowledgeDraftSchema):
    edited_title = st.text_input("Title", value=draft.title)
    edited_summary = st.text_area("Summary", value=draft.summary, height=80)
    edited_body = st.text_area("Body (Markdown)", value=draft.body_md, height=300)

    feedback = st.text_area("Feedback for the next refinement turn (optional)")
    refine_col, save_col, discard_col = st.columns(3)
    with refine_col:
        if st.button("Refine with feedback", disabled=not feedback):
            edited_kdoc = draft.model_copy(
                update={"title": edited_title, "summary": edited_summary, "body_md": edited_body}
            )
            try:
                provider = get_provider(provider_name, api_key)
                k_outcome2 = continue_knowledge_refinement(
                    provider=provider,
                    model=model,
                    transcript=astate.get("transcript", ()),
                    feedback=feedback,
                    edited_draft=edited_kdoc,
                    tool_context=tool_context,
                )
                astate["draft"] = k_outcome2.draft or edited_kdoc
                astate["transcript"] = k_outcome2.transcript
                astate["note"] = k_outcome2.note
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                st.error(f"Refinement failed: {exc}")
    with save_col:
        if st.button("💾 Save to my private bank"):
            try:
                kdoc_draft = KnowledgeDraft(
                    slug=draft.slug,
                    tier=QuestionTier.PRIVATE,
                    title=edited_title,
                    summary=edited_summary,
                    body_md=edited_body,
                    modules=draft.modules,
                    topics=draft.topics,
                    related_slugs=draft.related_slugs,
                    verification_level=VerificationLevel.AI_GENERATED,
                    source_url=draft.source_url,
                    origin="ai_generated",
                )
                knowledge_repo.create(kdoc_draft, author_id=user_id)
                st.success("Saved to your private bank.")
                st.session_state.pop("author_state", None)
                st.rerun()
            except BackendUnavailable:
                st.error("Could not reach the database. Please retry.")
    with discard_col:
        if st.button("Discard"):
            st.session_state.pop("author_state", None)
            st.rerun()
