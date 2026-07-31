"""In-app notification inbox. No email — see docs/DECISIONS.md D15.
Notifications are trigger-written only; this page only ever reads and marks
read_at, never inserts. See core/db/repositories/notifications.py.
"""

from __future__ import annotations

from uuid import UUID

import streamlit as st

from app.state import get_auth_user
from core.db.client import get_client_as
from core.db.errors import BackendUnavailable
from core.db.repositories.notifications import NotificationRepository

st.title("📥 Inbox")

user = get_auth_user()
if user is None:
    st.error("You must be signed in to view your Inbox.")
    st.stop()
user_id: UUID = user.id

client = get_client_as(user.access_token, user.refresh_token)
notification_repo = NotificationRepository(client)

try:
    page = notification_repo.list_for_user(user_id, limit=50)
except BackendUnavailable:
    st.info("Waking the database — this can take about 30 seconds. Please refresh shortly.")
    st.stop()

if page.items and st.button("Mark all as read"):
    notification_repo.mark_all_read(user_id)
    st.rerun()

if not page.items:
    st.caption("No notifications yet.")

for note in page.items:
    with st.container(border=True):
        marker = "🔵" if note.is_unread else "•"
        st.markdown(f"{marker} **{note.title}**")
        if note.body:
            st.caption(note.body)
        st.caption(f"{note.created_at:%Y-%m-%d %H:%M} · {note.kind.value}")
        if note.is_unread and st.button("Mark read", key=f"read_{note.id}"):
            notification_repo.mark_read(note.id, user_id=user_id)
            st.rerun()
