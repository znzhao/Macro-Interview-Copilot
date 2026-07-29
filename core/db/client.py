"""Cached Supabase client factory.

Always uses the anon key. The service-role key must never appear in this app —
it bypasses Row Level Security entirely (docs/DATA_SPEC.md #6.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


def _build_client(url: str, anon_key: str) -> Client:
    from supabase import create_client

    return create_client(url, anon_key)


def get_client() -> Client:
    """Return a process-wide cached Supabase client (anon key).

    Cached via st.cache_resource so exactly one client exists per process,
    per docs/UI_SPEC.md #3 (Streamlit runtime discipline).
    """
    import streamlit as st

    from core.config import get_settings

    @st.cache_resource
    def _cached() -> Client:
        settings = get_settings()
        return _build_client(str(settings.supabase.url), settings.supabase.anon_key)

    return _cached()


def get_client_as(access_token: str, refresh_token: str) -> Client:
    """Return a Supabase client authenticated as a specific user's session.

    Required for RLS to apply to that user's requests — a client built with only
    the anon key and no session behaves as an anonymous (unauthenticated) caller.
    Not cached: caller-specific, cheap to construct, and must not leak across users.
    """
    client = get_client()
    client.auth.set_session(access_token, refresh_token)
    return client
