"""Shared helpers for the repository layer.

No repository imports streamlit (docs/ARCHITECTURE.md #2). Callers apply caching.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from core.db.errors import BackendUnavailable, ConflictError, NotFound, PermissionDenied

T = TypeVar("T")

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def translate_errors(fn: Callable[[], T]) -> T:  # noqa: UP047 - py3.11 dev env compat
    """Run a Supabase call, translating known failure shapes into typed errors.

    Anything unrecognized becomes BackendUnavailable rather than leaking a raw
    postgrest/httpx exception up through the engine and UI layers.
    """
    try:
        return fn()
    except (NotFound, PermissionDenied, ConflictError, BackendUnavailable):
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad, then re-typed
        message = str(exc).lower()
        if "permission denied" in message or "row-level security" in message:
            raise PermissionDenied(str(exc)) from exc
        if "duplicate key" in message or "conflict" in message:
            raise ConflictError(str(exc)) from exc
        if "timeout" in message or "connection" in message or "unavailable" in message:
            raise BackendUnavailable(str(exc)) from exc
        raise BackendUnavailable(str(exc)) from exc
