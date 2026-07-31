"""Provider resolution and key validation. See docs/AI_SPEC.md #1.1, #1.1a.

The one place that knows all three provider names and how to construct an
adapter for one. Also reports per-provider capabilities so a caller whose
user holds a key for a provider without agent support can offer the one-shot
authoring path and a clear explanation instead of crashing.
"""

from __future__ import annotations

from core.llm.base import KeyStatus, LLMProvider, ProviderCapabilities

PROVIDER_NAMES = ("openai", "anthropic", "gemini")

# All three currently support both structured output and tool use — see the
# module docstrings on each adapter for the provider-specific mechanism.
# Declared per-provider (rather than assuming uniformity) precisely so that if
# a future provider is added without tool support, only this table changes.
CAPABILITIES: dict[str, ProviderCapabilities] = {
    "openai": ProviderCapabilities(structured_output=True, tool_use=True),
    "anthropic": ProviderCapabilities(structured_output=True, tool_use=True),
    "gemini": ProviderCapabilities(structured_output=True, tool_use=True),
}

DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-2.5-flash",
}


class UnknownProvider(ValueError):
    pass


def capabilities_for(provider: str) -> ProviderCapabilities:
    if provider not in CAPABILITIES:
        raise UnknownProvider(f"unknown provider {provider!r}; expected one of {PROVIDER_NAMES}")
    return CAPABILITIES[provider]


def get_provider(provider: str, api_key: str) -> LLMProvider:
    """Construct an adapter. The api_key is read from the caller's argument,
    never from anywhere global — see docs/DECISIONS.md D4: it lives in
    st.session_state for the browser session and is never persisted, logged,
    or passed to anything outside this call.
    """
    if provider == "openai":
        from core.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key)
    if provider == "anthropic":
        from core.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key)
    if provider == "gemini":
        from core.llm.gemini_provider import GeminiProvider

        return GeminiProvider(api_key)
    raise UnknownProvider(f"unknown provider {provider!r}; expected one of {PROVIDER_NAMES}")


def validate_key(provider: str, api_key: str) -> KeyStatus:
    try:
        instance = get_provider(provider, api_key)
    except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
        return KeyStatus(valid=False, message=str(exc))
    return instance.validate_key()
