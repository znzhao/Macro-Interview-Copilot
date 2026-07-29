"""Settings page. Profile fields are live in Phase 1; the LLM key UI is a
functional stub (session-state only) ahead of the Phase 2 provider adapters.
See docs/UI_SPEC.md #1.7.
"""

from __future__ import annotations

import streamlit as st

from app.state import (
    clear_llm_api_key,
    get_auth_user,
    get_llm_api_key,
    get_llm_provider,
    get_session_token_usage,
    set_llm_api_key,
)
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable
from core.db.repositories.profiles import ProfileRepository
from core.models.enums import ExperienceLevel, TargetRole
from core.models.profile import ProfilePatch

st.title("⚙️ Settings")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view Settings.")
    st.stop()

client = get_client_as(user.access_token, user.refresh_token)
repo = ProfileRepository(client)

try:
    profile = repo.get_or_raise(user.id)
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

st.subheader("Profile")
with st.form("profile_form"):
    display_name = st.text_input("Display name", value=profile.display_name or "")
    target_roles = st.multiselect(
        "Target roles",
        options=[r.value for r in TargetRole],
        default=[r.value for r in profile.target_roles],
    )
    experience_level = st.selectbox(
        "Experience level",
        options=[e.value for e in ExperienceLevel],
        index=[e.value for e in ExperienceLevel].index(profile.experience_level.value),
    )
    submitted = st.form_submit_button("Save profile")

if submitted:
    try:
        repo.update(
            user.id,
            ProfilePatch(
                display_name=display_name or None,
                target_roles=tuple(TargetRole(r) for r in target_roles),
                experience_level=ExperienceLevel(experience_level),
            ),
        )
        st.session_state.pop("profile", None)
        st.success("Profile saved.")
        st.rerun()
    except BackendUnavailable:
        st.error("Could not reach the database. Your changes were not saved — please retry.")

st.divider()

st.subheader("LLM API key")
st.caption(
    "Your key is used only in this browser session and is **never** written to the "
    "database, logs, or exported data. Mock interviews and AI-assisted question "
    "authoring are unavailable without one; browsing, notes, and favorites work fully "
    "without one. Full LLM provider support (evaluation, follow-ups) lands in Phase 2 "
    "— this key is stored and ready for it."
)

current_provider = get_llm_provider()
current_key = get_llm_api_key()

with st.form("llm_key_form"):
    provider = st.selectbox(
        "Provider",
        options=["openai", "anthropic", "gemini"],
        index=["openai", "anthropic", "gemini"].index(current_provider)
        if current_provider
        else 0,
    )
    api_key = st.text_input("API key", type="password", value="")
    save = st.form_submit_button("Save key for this session")

if save and api_key:
    set_llm_api_key(provider, api_key)
    st.success("Key saved for this session.")

if current_key:
    st.caption(f"A key is currently set for **{current_provider}**.")
    if st.button("Clear key"):
        clear_llm_api_key()
        st.rerun()
else:
    st.caption("No key currently set.")

st.caption(f"Session token usage so far: {get_session_token_usage():,}")

st.divider()

st.subheader("Data")
st.caption(
    "Export and account deletion are available once interview and evaluation data "
    "exist to export — Phase 2 and later. Deleting your account will anonymize "
    "(not delete) any community questions you've published, so other users' "
    "interview history stays interpretable."
)
