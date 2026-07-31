"""BYO-key prompt, validation, and the "no key set" banner — the single point
of truth for LLM key UX. See docs/UI_SPEC.md #2, docs/DECISIONS.md D4.

The key itself never leaves st.session_state (app/state.py) — this module
only reads/writes it through those typed accessors, same as every other page.
"""

from __future__ import annotations

from core.llm.base import KeyStatus
from core.llm.registry import PROVIDER_NAMES


def no_key_banner() -> None:
    """Delegates to the existing banner in empty_states.py so there is still
    exactly one wording for "no key set" across the app, not two.
    """
    from app.components.empty_states import no_llm_key_banner

    no_llm_key_banner()


def render_key_form() -> None:
    """Provider select, password-masked key entry, and a Test key button.
    Saves to session state only on an explicit Save — never on every rerun.
    """
    import streamlit as st

    from app.state import (
        clear_llm_api_key,
        get_llm_api_key,
        get_llm_provider,
        set_llm_api_key,
    )

    current_provider = get_llm_provider() or PROVIDER_NAMES[0]
    has_key = get_llm_api_key() is not None

    st.caption(
        "Your key is held in this browser session only — never written to the "
        "database, a log, or anywhere else. It is cleared the moment you sign "
        "out or close the tab."
    )

    with st.form("llm_key_form"):
        provider = st.selectbox(
            "Provider",
            PROVIDER_NAMES,
            index=PROVIDER_NAMES.index(current_provider),
        )
        api_key = st.text_input("API key", type="password", value="")
        col1, col2 = st.columns(2)
        with col1:
            save = st.form_submit_button("Save", use_container_width=True)
        with col2:
            test = st.form_submit_button("Save and test key", use_container_width=True)

    if not (save or test):
        if has_key:
            st.success(f"A key is set for **{current_provider}**.")
        return

    if not api_key:
        st.error("Enter a key before saving.")
        return

    set_llm_api_key(provider, api_key)

    if not test:
        st.success("Key saved for this session.")
        return

    with st.status(f"Validating your {provider} key...", expanded=False) as status:
        result = _validate(provider, api_key)
        if result.valid:
            status.update(label="Key is valid.", state="complete")
        else:
            status.update(label="Key validation failed.", state="error")

    if not result.valid:
        st.error(result.message or "The provider rejected this key.")
        clear_llm_api_key()


def _validate(provider: str, api_key: str) -> KeyStatus:
    from core.llm.registry import validate_key

    return validate_key(provider, api_key)
