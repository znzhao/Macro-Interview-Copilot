"""Settings page. Profile fields are live in Phase 1; the LLM key UI is a
functional stub (session-state only) ahead of the Phase 2 provider adapters.
See docs/UI_SPEC.md #1.7.
"""

from __future__ import annotations

import streamlit as st

from app.components.api_key_gate import render_key_form
from app.state import get_auth_user, get_session_token_usage
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
    "Mock interviews and AI-assisted question/knowledge authoring are unavailable "
    "without a key; browsing, notes, and favorites work fully without one."
)

render_key_form()

st.caption(f"Session token usage so far: {get_session_token_usage():,}")

st.divider()

st.subheader("Data")
st.caption(
    "Export and account deletion are available once interview and evaluation data "
    "exist to export — Phase 2 and later. Deleting your account will anonymize "
    "(not delete) any community questions you've published, so other users' "
    "interview history stays interpretable."
)
