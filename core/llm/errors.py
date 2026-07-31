"""Typed LLM errors. Raw provider SDK exceptions never propagate past the
provider adapters — see docs/ARCHITECTURE.md #5.1, docs/AI_SPEC.md #1.2.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all typed LLM errors."""


class LLMAuthError(LLMError):
    """The provider rejected the API key (401). Never retried — see
    docs/ARCHITECTURE.md #5: "Your API key was rejected." Clear from session.
    """


class LLMRateLimited(LLMError):
    """429 from the provider. One backoff retry, then surfaced to the user
    with the answer already persisted (docs/ARCHITECTURE.md #5).
    """


class LLMTimeout(LLMError):
    """The call exceeded timeout_s. Same handling as LLMRateLimited."""


class LLMSchemaError(LLMError):
    """The provider's structured output failed schema validation even after
    the one allowed repair retry (docs/AI_SPEC.md #1.2).
    """


class LLMToolArgError(LLMError):
    """A tool call's arguments could not be parsed as valid JSON matching the
    tool's schema. Fed back to the model as a tool result once; two
    consecutive failures on the same tool end the agent loop
    (docs/AI_SPEC.md #6.3, #7.3).
    """
