from __future__ import annotations

import abc
from typing import AsyncIterator


class BaseCrawler(abc.ABC):
    """Contract for walking a site/section and yielding page URLs to visit."""

    @abc.abstractmethod
    def crawl(self, seed_url: str) -> AsyncIterator[str]:
        """Yield every URL discovered starting from *seed_url*."""
