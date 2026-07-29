"""Typed repository errors. Raw postgrest/supabase exceptions never propagate
past the repository layer — see docs/DATA_SPEC.md #8.2.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for all typed repository errors."""


class NotFound(RepositoryError):
    pass


class PermissionDenied(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


class BackendUnavailable(RepositoryError):
    """Raised when Supabase is unreachable or paused (free-tier idle).

    See docs/ARCHITECTURE.md #5 for the required UI behavior on this error.
    """
