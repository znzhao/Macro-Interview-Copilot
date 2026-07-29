"""Shared generic types used across domain models and repositories."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - py3.11 dev env compat
    """A bounded page of results. No repository method returns an unbounded list."""

    model_config = ConfigDict(frozen=True)

    items: tuple[T, ...]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
