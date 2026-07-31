"""Supabase Auth wrapper.

Exposes current_user() for pages to check who is signed in. The session is
kept in st.session_state (per-user, not module-global — docs/UI_SPEC.md #3.1).

Magic-link sign-in uses the **token_hash** flow, not Supabase's default. The
default returns tokens in the URL fragment (`#access_token=...`), which browsers
never send to the server — so Streamlit, rendering server-side, cannot read them
and sign-in silently fails. token_hash puts a single-use token in the query
string instead, and is stateless, so it survives the new browser tab that an
email link typically opens. This requires the Supabase email templates to be
edited; see docs/DEPLOYMENT.md section 4.3.

Google OAuth still uses the `?code=` PKCE exchange. See docs/DATA_SPEC.md #6.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast, get_args
from uuid import UUID

# Mirrors supabase-py's EmailOtpType. Supabase sends "signup" for a first-time
# user's confirmation email and "magiclink" for subsequent sign-ins, so the app
# must accept whichever the email template passes back.
EmailOtpType = Literal["signup", "invite", "magiclink", "recovery", "email_change", "email"]
_VALID_OTP_TYPES: frozenset[str] = frozenset(get_args(EmailOtpType))


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str | None
    access_token: str
    refresh_token: str


def current_user() -> AuthUser | None:
    """Return the signed-in user for this browser session, or None."""
    import streamlit as st

    user = st.session_state.get("auth_user")
    if user is None:
        return None
    if not isinstance(user, AuthUser):
        raise TypeError(f"session_state['auth_user'] holds unexpected type {type(user)!r}")
    return user


class EmailConfirmationRequired(RuntimeError):
    """Sign-up succeeded but Supabase withheld a session pending email confirmation.

    Raised when the project still has Authentication -> Providers -> Email ->
    "Confirm email" enabled. That confirmation email uses Supabase's default
    template, whose link returns tokens in the URL fragment that this app cannot
    read (see module docstring), so the user would be stuck. Turn the setting
    off, or configure custom SMTP and use the magic-link path instead.
    """


def _session_to_user(result: object) -> AuthUser:
    """Build an AuthUser from a supabase AuthResponse, or raise if incomplete."""
    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    if session is None or user is None:
        raise RuntimeError("authentication did not return a session")
    return AuthUser(
        id=UUID(user.id),
        email=user.email,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def sign_up_with_password(email: str, password: str) -> AuthUser:
    """Create an account and return an immediately-usable session.

    Requires "Confirm email" to be OFF in the Supabase dashboard; otherwise
    Supabase returns a user with no session and this raises
    EmailConfirmationRequired.
    """
    import streamlit as st

    from core.db.client import get_client

    result = get_client().auth.sign_up({"email": email, "password": password})
    if getattr(result, "session", None) is None:
        raise EmailConfirmationRequired(
            "Supabase created the account but is holding the session until the "
            "email address is confirmed. Disable Authentication -> Providers -> "
            "Email -> 'Confirm email' in the Supabase dashboard, then sign in."
        )

    user = _session_to_user(result)
    st.session_state["auth_user"] = user
    return user


def sign_in_with_password(email: str, password: str) -> AuthUser:
    """Sign in an existing account. No email round-trip, so nothing to configure."""
    import streamlit as st

    from core.db.client import get_client

    result = get_client().auth.sign_in_with_password({"email": email, "password": password})
    user = _session_to_user(result)
    st.session_state["auth_user"] = user
    return user


def sign_in_with_magic_link(email: str, *, redirect_to: str) -> None:
    """Trigger a magic-link email via Supabase Auth.

    NOT wired into the UI by default. Two prerequisites, both dashboard-side:
      1. Custom SMTP configured — Supabase's free built-in mailer is rate limited
         to a handful of messages per hour AND locks email template editing.
      2. The email templates edited per docs/DEPLOYMENT.md section 4.3, so the
         link carries `?token_hash=` rather than the unreadable `#access_token=`.

    With those done, `complete_session_from_token_hash` handles the callback.
    """
    from core.db.client import get_client

    client = get_client()
    client.auth.sign_in_with_otp({"email": email, "options": {"email_redirect_to": redirect_to}})


def start_google_oauth(*, redirect_to: str) -> str:
    """Return the redirect URL to start the Google OAuth flow."""
    from core.db.client import get_client

    client = get_client()
    result = client.auth.sign_in_with_oauth(
        {"provider": "google", "options": {"redirect_to": redirect_to}}
    )
    return str(result.url)


def complete_session_from_token_hash(token_hash: str, otp_type: str = "email") -> AuthUser:
    """Verify a magic-link `token_hash` and store the resulting session.

    This is the flow that actually works under Streamlit. Supabase's *default*
    magic link returns tokens in the URL fragment (`#access_token=...`), which
    browsers never transmit to the server — so a server-rendered framework like
    Streamlit can never see them, and the user silently stays signed out.

    The token_hash flow instead puts a single-use token in the query string,
    which `st.query_params` can read. It is also stateless: unlike PKCE there is
    no code_verifier to carry across a script rerun or a newly opened tab, and
    email links very often open in a new tab.

    Requires the Supabase email templates to link to
    `{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=...` — see
    docs/DEPLOYMENT.md section 4.3.
    """
    import streamlit as st

    from core.db.client import get_client

    if otp_type not in _VALID_OTP_TYPES:
        raise ValueError(
            f"unsupported OTP type {otp_type!r}; expected one of {sorted(_VALID_OTP_TYPES)}"
        )
    validated_type = cast(EmailOtpType, otp_type)

    client = get_client()
    result = client.auth.verify_otp({"token_hash": token_hash, "type": validated_type})
    if result.session is None or result.user is None:
        raise RuntimeError("the sign-in link was invalid or has already been used")

    user = AuthUser(
        id=UUID(result.user.id),
        email=result.user.email,
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    )
    st.session_state["auth_user"] = user
    return user


def complete_session_from_code(code: str) -> AuthUser:
    """Exchange a PKCE auth code (`?code=`) for a session.

    Used by the Google OAuth path. Note this requires the Supabase client to
    have been created with flow_type="pkce" and to still hold the code_verifier
    it generated at sign-in — see the caveat in PHASE_TRACKER.md. The magic-link
    path deliberately uses `complete_session_from_token_hash` instead, which
    needs no such carried state.
    """
    import streamlit as st

    from core.db.client import get_client

    client = get_client()
    result = client.auth.exchange_code_for_session({"auth_code": code})  # type: ignore[typeddict-item]
    if result.session is None or result.user is None:
        raise RuntimeError("could not resolve a session from the auth code")

    user = AuthUser(
        id=UUID(result.user.id),
        email=result.user.email,
        access_token=result.session.access_token,
        refresh_token=result.session.refresh_token,
    )
    st.session_state["auth_user"] = user
    return user


def sign_out() -> None:
    import streamlit as st

    from core.db.client import get_client

    get_client().auth.sign_out()
    st.session_state.pop("auth_user", None)
