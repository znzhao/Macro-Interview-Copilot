"""Unit tests for core.llm.registry."""

from __future__ import annotations

import pytest

from core.llm.registry import (
    CAPABILITIES,
    DEFAULT_MODELS,
    PROVIDER_NAMES,
    UnknownProvider,
    get_provider,
)


def test_all_provider_names_have_capabilities_and_default_models() -> None:
    for name in PROVIDER_NAMES:
        assert name in CAPABILITIES
        assert name in DEFAULT_MODELS


def test_get_provider_rejects_unknown_name() -> None:
    with pytest.raises(UnknownProvider):
        get_provider("not-a-real-provider", "sk-fake")


def test_get_provider_constructs_openai_adapter() -> None:
    from core.llm.openai_provider import OpenAIProvider

    provider = get_provider("openai", "sk-fake")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_get_provider_constructs_anthropic_adapter() -> None:
    from core.llm.anthropic_provider import AnthropicProvider

    provider = get_provider("anthropic", "sk-fake")
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"


def test_get_provider_constructs_gemini_adapter() -> None:
    from core.llm.gemini_provider import GeminiProvider

    provider = get_provider("gemini", "sk-fake")
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"
