"""Admin page placeholder. Full moderation queue, tier promotion, bulk
authoring, and bank-health stats ship in Phase 3 — see docs/UI_SPEC.md #1.8.

Rendered only when profiles.is_admin is set (streamlit_app.py navigation),
but that is a UI convenience, not the authorization boundary — RLS is
(docs/DATA_SPEC.md #6.2). This page still only ever reads/writes through
RLS-scoped repository calls.
"""

from __future__ import annotations

import streamlit as st

st.title("🛡️ Admin")
st.info(
    "The moderation queue, question tier promotion, bulk AI authoring, and "
    "bank-health dashboard ship in Phase 3 (see PHASE_TRACKER.md). "
    "You're seeing this page because your profile is flagged as admin."
)
