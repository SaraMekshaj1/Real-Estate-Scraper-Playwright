from __future__ import annotations
import logging
from typing import Optional
from app.config.settings import Settings
from app.services.crawl_service import CrawlService
from app.services.export_service import ExportService
from app.services.scraping_service import ScrapingService
from monitoring.run_monitor import RunMonitor
from monitoring.scrape_statistics import ScrapeStatistics
from app.services.deduplication_service import DeduplicationService
from app.models.run_outcome import RunOutcome

class ScraperEngine:
    def __init__(
        self,
        crawl_service: CrawlService,
        scraping_service: ScrapingService,
        export_service: ExportService,
        statistics: ScrapeStatistics,
        monitor: RunMonitor,
        settings: Settings,
        logger: logging.Logger,
        dedup: Optional[DeduplicationService] = None,
    ) -> None:
        self._crawl_service = crawl_service
        self._scraping_service = scraping_service
        self._export_service = export_service
        self._statistics = statistics
        self._monitor = monitor
        self._settings = settings
        self._logger = logger
        self._dedup = dedup

    async def run(self) -> None:
        self._monitor.start()
        self._logger.info("Starting scrape of %s", self._settings.base_url)

        if self._dedup is not None:
            self._dedup.begin_run()

        self._export_service.start()
        scraped_count = 0
        crashed_error_count = 0
        outcome = RunOutcome.INTERRUPTED

        try:
            async for page_url, page_content, context in self._crawl_service.fetch_pages(
                self._settings.base_url
            ):
                items = list(self._scraping_service.process_page(page_url, page_content, context))
                if not items:
                    continue

                self._export_service.export_batch(items)
                scraped_count += len(items)
                for _ in items:
                    self._statistics.record_success()

                if self._dedup is not None:
                    self._dedup.mark_exported(page_url)

            outcome = RunOutcome.COMPLETED
        except Exception:
            crashed_error_count += 1
            raise
        finally:
            self._export_service.finish()
            if self._dedup is not None:
            # A run can "complete" with zero crashes and still have left a
            # pile of skipped URLs behind (circuit breaker, transient
            # errors, etc.) — those live in CrawlService's failed-url
            # store, not in an exception. Both count toward whether the
            # NEXT run should treat this one as clean or as needing resume.
                total_errors = crashed_error_count + self._crawl_service.failed_count()
                self._dedup.end_run(outcome, scrape_error_count=total_errors)

        self._logger.info(
            "Scrape complete: %d item(s) collected, %d failed url(s) pending retry",
            scraped_count, self._crawl_service.failed_count(),
        )
        self._monitor.finish(scraped=scraped_count, expected=self._statistics.expected)