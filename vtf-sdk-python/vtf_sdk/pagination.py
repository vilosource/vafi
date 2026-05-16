"""Pagination types for the vtf SDK."""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PagedResult(BaseModel, Generic[T]):
    """Paginated API response envelope."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    has_more: bool = False
    next_cursor: str | None = None
    previous_cursor: str | None = None
