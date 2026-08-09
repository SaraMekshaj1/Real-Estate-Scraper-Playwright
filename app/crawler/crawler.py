from __future__ import annotations
import logging
from typing import AsyncIterator, Optional
from app.abstraction.base_client import BaseClient
from app.abstraction.base_crawler import BaseCrawler
from app.abstraction.base_paginator import BasePaginator


class Crawler(BaseCrawler):
    """
    Generic paginated crawler: fetches a seed URL, hands the raw content
    to a paginator to decide the next URL, and repeats until there's no
    next page or `max_pages` is hit.

    This loop stays the same across projects — pagination *strategy*
    lives in the injected BasePaginator implementation (NoOpPaginator
    for a single seed page, Paginator for ?page=N/"next"-link style).
    """

    def __init__(
        self,
        client: BaseClient,
        paginator: BasePaginator,
        max_pages: int = 0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._client = client
        self._paginator = paginator
        self._max_pages = max_pages
        self._logger = logger or logging.getLogger(__name__)

    async def crawl(self, seed_url: str) -> AsyncIterator[str]:
        url: Optional[str] = seed_url
        pages_visited = 0

        while url:

            try:
                page_content = await self._client.get(url)
            except Exception as exc:  # noqa: BLE001
                # A failure here is checking for a NEXT page, not the
                # scrape itself — degrade gracefully rather than
                # crashing a run that may have already exported data.
                self._logger.warning(
                    "Couldn't check for a next page after %s (%s) — stopping pagination here.",
                    url, exc,
                )
                break
            yield url, page_content
            pages_visited += 1

            if self._max_pages and pages_visited >= self._max_pages:
                            self._logger.info("Reached max_pages=%s, stopping.", self._max_pages)
                            break

            if not self._paginator.has_next(page_content):
                break

            url = self._paginator.next_url(url, page_content)
