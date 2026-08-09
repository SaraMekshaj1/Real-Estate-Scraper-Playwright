from __future__ import annotations
import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
from app.abstraction.base_client import BaseClient
from app.abstraction.base_crawler import BaseCrawler
from app.abstraction.base_link_extractor import BaseLinkExtractor
from app.exceptions.scraper_exceptions import PageNotFoundError
from app.services.deduplication_service import DeduplicationService
from app.storage.failed_url_store import FailedUrlStore, is_retryable,full_error_text


class CrawlService:
    def __init__(
        self,
        client: BaseClient,
        crawler: BaseCrawler,
        link_extractor: BaseLinkExtractor,
        detail_link_extractor: Optional[BaseLinkExtractor] = None,
        detail_content_validator: Optional[Callable[[str], bool]] = None,
        max_workers: int = 5,
        logger: Optional[logging.Logger] = None,
        dedup: Optional[DeduplicationService] = None,
        failed_url_store: Optional[FailedUrlStore] = None,
    ) -> None:
        self._client = client
        self._crawler = crawler
        self._link_extractor = link_extractor
        self._detail_link_extractor = detail_link_extractor
        self._detail_content_validator = detail_content_validator
        self._max_workers = max_workers
        self._logger = logger or logging.getLogger(__name__)
        self._dedup = dedup
        self._failed_url_store = failed_url_store

    

    def failed_count(self) -> int:
        """Used by ScraperEngine to decide the run outcome — a run with
        entries sitting in the failed-url store is NOT a clean COMPLETED
        run, even though nothing crashed."""
        return len(self._failed_url_store) if self._failed_url_store is not None else 0

    async def fetch_pages(self, seed_url: str) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        async for listing_url, listing_content in self._crawler.crawl(seed_url):
            self._logger.info("Visiting listing page: %s", listing_url)

            links = self._link_extractor.extract(listing_content, listing_url)
            self._logger.info("Found %d link(s) on %s", len(links), listing_url)

            if self._dedup is not None and self._detail_link_extractor is None:
                before = len(links)
                fresh = set(self._dedup.filter_new_urls(url for url, _ in links))
                links = [(url, ctx) for url, ctx in links if url in fresh]
                if before != len(links):
                    self._logger.info("Resume: skipped %d already-exported link(s)", before - len(links))

            async for result in self._process_links(links):
                yield result

    async def _process_links(
        self, links: List[Tuple[str, Dict[str, Any]]]
    ) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        if not links:
            return

        work_queue: asyncio.Queue = asyncio.Queue()
        for link in links:
            work_queue.put_nowait(link)

        result_queue: "asyncio.Queue[Optional[Tuple[str, str, Dict[str, Any]]]]" = asyncio.Queue()
        total = len(links)
        done_count = 0
        progress_lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal done_count
            while True:
                try:
                    target_url, context = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                result = await self._fetch_one(target_url, context)
                async with progress_lock:
                    done_count += 1
                    if done_count % 25 == 0 or done_count == total:
                        self._logger.info("Progress: %d/%d item(s) processed", done_count, total)
                await result_queue.put(result)

        pool_size = min(self._max_workers, total)
        workers = [asyncio.create_task(worker()) for _ in range(pool_size)]

        try:
            for _ in range(total):
                result = await result_queue.get()
                if result is not None:
                    yield result
        finally:
            await asyncio.gather(*workers, return_exceptions=True)

    # ── Stage 1 (hop 2): fetch the listing page ──────────────────

    async def _fetch_listing_page(self, target_url: str,  context: Dict[str, Any]) -> Optional[str]:
        try:
            return await self._client.get(target_url)
        except PageNotFoundError:
            self._logger.debug("404 (skipping, not an error): %s", target_url)
            return None
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Skipping %s: %s", target_url, exc)
            error_text = full_error_text(exc)
            if self._failed_url_store is not None and is_retryable(error_text):
                await self._failed_url_store.record(target_url, error_text, stage="listing_page", context=context)
            return None

    # ── Stage 2 (hop 3): fetch the detail page given its URL ────────────

    async def _fetch_detail_page(
        self, detail_url: str, referer: str, context: Dict[str, Any]
    ) -> Optional[str]:
        if self._dedup is not None and not self._dedup.is_new_url(detail_url):
            self._logger.debug("Resume: already exported, skipping detail fetch: %s", detail_url)
            return None
        try:
            return await self._client.get(
                detail_url, referer=referer, content_validator=self._detail_content_validator
            )
        except PageNotFoundError:
            self._logger.debug("404 on detail page (skipping): %s", detail_url)
            return None
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Skipping detail page %s: %s", detail_url, exc)
            error_text = full_error_text(exc)
            if self._failed_url_store is not None and is_retryable(error_text):
                await self._failed_url_store.record(
                 detail_url, error_text, stage="detail_page", context=context, referer=referer
                )
            return None

    async def _fetch_one(
        self, target_url: str, context: Dict[str, Any]
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        self._logger.debug("Fetching page: %s", target_url)
        content = await self._fetch_listing_page(target_url, context)
        if content is None:
            return None

        if self._detail_link_extractor is not None:
            detail_links = self._detail_link_extractor.extract(content, target_url)
            if not detail_links:
                self._logger.info("No listings on %s — confirmed empty, not an error", target_url)
                if self._dedup is not None:
                    self._dedup.mark_checked_empty(target_url)
                return None

            detail_url, extra_context = detail_links[0]
            merged_context = {**context, **extra_context}

            self._logger.debug("Following detail link: %s -> %s", target_url, detail_url)
            content = await self._fetch_detail_page(detail_url, target_url, merged_context)
            if content is None:
                return None

            return detail_url, content, merged_context

        return target_url, content, context

    # ── Public entry points used by the retry script ────────────────────

    async def retry_from_listing_page(
        self, listing_url: str, context: Dict[str, Any]
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """Re-runs the FULL 2-hop chain for one listing URL, from scratch."""
        return await self._fetch_one(listing_url, context)

    async def retry_from_detail_page(
        self, detail_url: str, referer: str, context: Dict[str, Any]
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """Re-fetches ONLY the detail page — used when a detail_page-stage
        failure already has everything else it needs (context, referer)."""
        content = await self._fetch_detail_page(detail_url, referer, context)
        if content is None:
            return None
        return detail_url, content, context