from __future__ import annotations

import abc
from typing import Any, Optional


class BasePaginator(abc.ABC):
    """
    Contract for deciding whether a listing page has a "next page" and,
    if so, what its URL is. Operates on already-fetched page content —
    no I/O happens here, only content inspection.

    Swap this out per project: NoOpPaginator (single seed page, e.g. a
    page whose data lives in an embedded <script>), Paginator
    (?page=N / "next" link style pagination), or a custom
    infinite-scroll-aware implementation.
    """

    @abc.abstractmethod
    def has_next(self, current_page: Any) -> bool:
        """Return True if there is a next page to visit."""

    @abc.abstractmethod
    def next_url(self, current_url: str, current_page: Any) -> Optional[str]:
        """Return the next page's URL, or None if there isn't one."""
