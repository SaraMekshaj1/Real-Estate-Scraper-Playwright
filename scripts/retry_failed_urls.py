# scripts/retry_failed_urls.py
from __future__ import annotations
import asyncio
import logging
from app.container.container import Container
from app.services.crawl_service import CrawlService
from app.services.scraping_service import ScrapingService
from app.services.export_service import ExportService
from app.services.deduplication_service import DeduplicationService
from app.storage.failed_url_store import FailedUrlEntry
from typing import Optional

async def _retry_entry(
    crawl_service: CrawlService,
    scraping_service: ScrapingService,
    export_service: ExportService,
    dedup: Optional[DeduplicationService],
    logger: logging.Logger,
    entry: FailedUrlEntry,
) -> bool:
    """Returns True on success (item exported OR confirmed-empty page)."""
    if entry["stage"] == "listing_page":
        result = await crawl_service.retry_from_listing_page(entry["url"], entry["context"])
    elif entry["stage"] == "detail_page":
        result = await crawl_service.retry_from_detail_page(
            entry["url"], entry.get("referer") or entry["url"], entry["context"]
        )
    else:
        logger.warning("Unknown stage %r for %s — skipping", entry["stage"], entry["url"])
        return False

    if result is None:
        if dedup is not None and dedup.is_checked_empty(entry["url"]):
            logger.info("Resolved as confirmed-empty, removing from retry queue: %s", entry["url"])
            return True
        return False

    page_url, content, context = result
    items = list(scraping_service.process_page(page_url, content, context))
    if items:
        export_service.export_batch(items)
    if dedup is not None:
        dedup.mark_exported(page_url)
    return True


async def main(max_attempts: int = 5) -> None:
    container = Container()
    logger = container.logger
    failed_store = container.failed_url_store()

    pending = failed_store.pending(max_attempts)
    if not pending:
        logger.info("No pending failed URLs to retry.")
        return

    by_stage: dict[str, int] = {}
    for e in pending:
        by_stage[e["stage"]] = by_stage.get(e["stage"], 0) + 1
    logger.info("Retrying %d URL(s): %s", len(pending), by_stage)

    # Build ONCE, reuse for every entry — same instances throughout this run.
    crawl_service = container.crawl_service()
    scraping_service = container.scraping_service()
    export_service = container.export_service()
    dedup = container.deduplication_service()

    export_service.start()
    succeeded = 0
    try:
        for entry in pending:
            ok = await _retry_entry(
                crawl_service, scraping_service, export_service, dedup, logger, entry
            )
            if ok:
                await failed_store.remove(entry["url"])
                succeeded += 1
    finally:
        export_service.finish()
        await container.client().close()

    logger.info(
        "Retry pass complete: %d/%d succeeded, %d still pending",
        succeeded, len(pending), len(failed_store),
    )


if __name__ == "__main__":
    asyncio.run(main())