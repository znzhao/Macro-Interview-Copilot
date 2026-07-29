"""Dashboard shell. Full metrics (score trends, weak topics, radar) land in
Phase 2/3 once evaluations exist. Phase 1 ships the empty-state onboarding
flow and favorites/notes summary — see docs/UI_SPEC.md #1.1.
"""

from __future__ import annotations

import streamlit as st

from app.components.empty_states import onboarding_dashboard
from app.state import get_auth_user, get_llm_api_key
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable
from core.db.repositories.favorites import FavoriteRepository

st.title("🏠 Dashboard")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view the Dashboard.")
    st.stop()

profile = st.session_state.get("profile")

client = get_client_as(user.access_token, user.refresh_token)

try:
    favorites = FavoriteRepository(client).list_for_user(user.id)
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

has_target_roles = bool(profile and profile.target_roles)
has_llm_key = get_llm_api_key() is not None

if not has_target_roles and not has_llm_key and not favorites:
    onboarding_dashboard()
else:
    col1, col2, col3 = st.columns(3)
    col1.metric("Favorited questions", len(favorites))
    col2.metric("Sessions completed", 0, help="Interview mode ships in Phase 2.")
    col3.metric("Average score", "—", help="Available once you've completed a session.")

    st.caption(
        "Full progress tracking — score trends, weak-topic detection, and session "
        "history — activates once mock interviews ship in Phase 2."
    )

    if not has_llm_key:
        from app.components.empty_states import no_llm_key_banner

        no_llm_key_banner()
