"""Application configuration.

Loaded from st.secrets exactly once, validated eagerly, and exposed as a single
Settings object. No other module reads st.secrets or os.getenv directly —
this is the one entry point (see docs/IMPLEMENTATION_GUIDE.md #2).

Fails loudly on a missing or malformed value rather than degrading silently.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SupabaseSettings(BaseModel):
    url: HttpUrl
    anon_key: str = Field(min_length=20)


class AppSettings(BaseModel):
    environment: str = "development"
    admin_emails: tuple[str, ...] = ()

    # The app's own public URL. Supabase Auth redirects the browser back here
    # after a magic link or OAuth sign-in, so it must match exactly one of the
    # Redirect URLs configured in the Supabase dashboard.
    app_url: HttpUrl = HttpUrl("http://localhost:8501")

    @field_validator("environment")
    @classmethod
    def _environment_known(cls, v: str) -> str:
        if v not in ("development", "production"):
            raise ValueError(f"unknown environment: {v!r}")
        return v


class Settings(BaseModel):
    supabase: SupabaseSettings
    app: AppSettings

    # Default models, chosen for cost-efficiency. Overridable per-user in Settings.
    # See docs/AI_SPEC.md #1.2.
    default_models: dict[str, str] = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-5",
        "gemini": "gemini-2.5-flash",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings from st.secrets. Cached for the process lifetime.

    Import streamlit lazily so core.config stays importable in tests without
    a running Streamlit context.
    """
    import streamlit as st

    try:
        return Settings.model_validate(dict(st.secrets))
    except Exception as exc:  # noqa: BLE001 - re-raised with actionable context
        raise RuntimeError(
            "Invalid or missing configuration in .streamlit/secrets.toml. "
            "Copy .streamlit/secrets.toml.example and fill in real values. "
            f"Underlying error: {exc}"
        ) from exc
