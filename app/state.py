"""Typed st.session_state accessors.

All session state keys are declared here — no string literals scattered
across pages. See docs/UI_SPEC.md #3.1.
"""

from __future__ import annotations

from core.auth import AuthUser

_AUTH_USER_KEY = "auth_user"
_LLM_API_KEY_KEY = "llm_api_key"
_LLM_PROVIDER_KEY = "llm_provider"
_TOKEN_USAGE_KEY = "session_token_usage"


def get_auth_user() -> AuthUser | None:
    import streamlit as st

    user = st.session_state.get(_AUTH_USER_KEY)
    return user if isinstance(user, AuthUser) else None


def set_auth_user(user: AuthUser) -> None:
    import streamlit as st

    st.session_state[_AUTH_USER_KEY] = user


def clear_auth_user() -> None:
    import streamlit as st

    st.session_state.pop(_AUTH_USER_KEY, None)


def get_llm_api_key() -> str | None:
    """The user's own LLM key. Session-memory only — never persisted (D4)."""
    import streamlit as st

    key = st.session_state.get(_LLM_API_KEY_KEY)
    return key if isinstance(key, str) and key else None


def set_llm_api_key(provider: str, api_key: str) -> None:
    import streamlit as st

    st.session_state[_LLM_PROVIDER_KEY] = provider
    st.session_state[_LLM_API_KEY_KEY] = api_key


def clear_llm_api_key() -> None:
    import streamlit as st

    st.session_state.pop(_LLM_API_KEY_KEY, None)
    st.session_state.pop(_LLM_PROVIDER_KEY, None)


def get_llm_provider() -> str | None:
    import streamlit as st

    provider = st.session_state.get(_LLM_PROVIDER_KEY)
    return provider if isinstance(provider, str) else None


def get_session_token_usage() -> int:
    import streamlit as st

    usage = st.session_state.get(_TOKEN_USAGE_KEY, 0)
    return int(usage) if isinstance(usage, int) else 0


def add_session_token_usage(tokens: int) -> None:
    import streamlit as st

    st.session_state[_TOKEN_USAGE_KEY] = get_session_token_usage() + tokens
