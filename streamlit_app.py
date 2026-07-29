"""Entry point. Auth gate + navigation only — no business logic here.
See docs/UI_SPEC.md, docs/ARCHITECTURE.md #5 (global error handling rules).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.state import clear_auth_user, get_auth_user, set_auth_user
from core.auth import (
    EmailConfirmationRequired,
    complete_session_from_code,
    complete_session_from_token_hash,
    sign_in_with_password,
    sign_up_with_password,
)
from core.db.client import get_client
from core.db.errors import BackendUnavailable
from core.db.repositories.profiles import ProfileRepository

st.set_page_config(page_title="Macro Interview Copilot", page_icon="📈", layout="wide")


def _handle_auth_callback() -> None:
    """Complete a sign-in that redirected back here.

    Two shapes are handled:
      ?token_hash=...&type=...   magic link (see core.auth for why, not `#`)
      ?code=...                  OAuth / PKCE

    Note that Supabase's *default* magic-link template returns tokens in the URL
    fragment (`#access_token=...`), which the browser never sends to the server.
    Streamlit therefore cannot see them, and sign-in silently fails. The email
    templates must be pointed at `?token_hash=` — docs/DEPLOYMENT.md section 4.3.
    """
    if get_auth_user() is not None:
        return

    token_hash = st.query_params.get("token_hash")
    code = st.query_params.get("code")
    if not token_hash and not code:
        return

    try:
        if token_hash:
            otp_type = st.query_params.get("type") or "email"
            user = complete_session_from_token_hash(token_hash, otp_type)
        else:
            assert code is not None
            user = complete_session_from_code(code)
        set_auth_user(user)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not re-raised
        st.error(f"Sign-in failed: {exc}")
        st.query_params.clear()
        return

    st.query_params.clear()
    st.rerun()


def _render_landing_page() -> None:
    st.title("📈 Macro Interview Copilot")
    st.caption(
        "AI-powered interview training for global macro hedge funds, central banks, "
        "and international financial institutions."
    )

    col1, col2 = st.columns([1, 1])

    with col1:
        sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])

        with sign_in_tab:
            with st.form("sign_in_form"):
                email = st.text_input("Email", key="signin_email")
                password = st.text_input("Password", type="password", key="signin_password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)
            if submitted:
                if not email or not password:
                    st.error("Enter both an email and a password.")
                else:
                    try:
                        set_auth_user(sign_in_with_password(email, password))
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                        st.error(f"Sign-in failed: {exc}")

        with sign_up_tab:
            with st.form("sign_up_form"):
                new_email = st.text_input("Email", key="signup_email")
                new_password = st.text_input(
                    "Password",
                    type="password",
                    key="signup_password",
                    help="At least 6 characters.",
                )
                created = st.form_submit_button("Create account", use_container_width=True)
            if created:
                if not new_email or not new_password:
                    st.error("Enter both an email and a password.")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        set_auth_user(sign_up_with_password(new_email, new_password))
                        st.rerun()
                    except EmailConfirmationRequired as exc:
                        st.warning(str(exc))
                    except Exception as exc:  # noqa: BLE001 - shown, not re-raised
                        st.error(f"Could not create account: {exc}")

        st.caption(
            "Your LLM API key is never stored — it lives in your browser session only. "
            "See Settings for details once you're signed in."
        )

    with col2:
        st.subheader("Preview the question bank")
        try:
            from core.db.repositories.questions import QuestionRepository
            from core.models.enums import QuestionTier
            from core.models.question import QuestionFilters

            repo = QuestionRepository(get_client())
            page = repo.search(
                filters=QuestionFilters(tiers=(QuestionTier.VERIFIED,)), limit=5
            )
            for q in page.items:
                st.markdown(f"- **{q.question}** · `{q.module.value}`")
            if not page.items:
                st.caption("No questions available yet.")
        except BackendUnavailable:
            st.info("Waking the database — this can take about 30 seconds. Try again shortly.")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Preview unavailable: {exc}")


def _ensure_profile_loaded() -> None:
    user = get_auth_user()
    if user is None:
        return
    if "profile" in st.session_state:
        return
    try:
        from core.db.client import get_client_as

        client = get_client_as(user.access_token, user.refresh_token)
        profile = ProfileRepository(client).get_or_raise(user.id)
        st.session_state["profile"] = profile
    except BackendUnavailable:
        st.error("Waking the database — this can take about 30 seconds. Please refresh.")
        st.stop()


def _build_navigation() -> Any:  # noqa: ANN401 - st.navigation() has no exported type
    profile = st.session_state.get("profile")
    is_admin = bool(profile and profile.is_admin)

    pages = [
        st.Page("app/pages/1_Dashboard.py", title="Dashboard", icon="🏠"),
        st.Page("app/pages/2_Question_Bank.py", title="Question Bank", icon="📚"),
        st.Page("app/pages/7_Settings.py", title="Settings", icon="⚙️"),
    ]
    if is_admin:
        pages.append(st.Page("app/pages/9_Admin.py", title="Admin", icon="🛡️"))

    return st.navigation(pages)


def main() -> None:
    _handle_auth_callback()

    user = get_auth_user()
    if user is None:
        _render_landing_page()
        return

    _ensure_profile_loaded()

    with st.sidebar:
        st.caption(f"Signed in as {user.email or user.id}")
        if st.button("Sign out"):
            clear_auth_user()
            st.session_state.pop("profile", None)
            st.rerun()

    nav = _build_navigation()
    nav.run()


main()
