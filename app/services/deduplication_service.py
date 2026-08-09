from __future__ import annotations
import logging
from typing import Iterable, List
from app.abstraction.base_checkpoint_store import BaseCheckpointStore
from app.models.run_outcome import RunOutcome
from app.utils.logger import Metrics

logger = logging.getLogger("scraper")

_EXPORTED_KEY = "exported:{}"
_RUN_STATE_KEY = "run_in_progress"
_LAST_RUN_ERRORS_KEY = "last_run_had_errors"
_LAST_OUTCOME_KEY = "last_run_outcome"
_CHECKED_EMPTY_KEY = "checked_empty:{}"

class DeduplicationService:
    """
    Tracks which detail-page URLs have already been exported, so a
    restarted run skips work already durable on disk instead of
    re-fetching and re-exporting it.

    Dedup key = the FINAL detail-page URL a record was scraped from —
    the same url CrawlService.fetch_pages() yields and ScraperEngine
    passes to export. Also owns run-lifecycle bookkeeping so
    ScraperEngine never touches raw checkpoint keys directly.
    """

    def __init__(self, store: BaseCheckpointStore, metrics: Metrics) -> None:
        self._store = store
        self._metrics = metrics

    # ── Pre-fetch check (skips the network call entirely) ──────────────

    def is_new_url(self, url: str) -> bool:
        already_done = self._store.exists(_EXPORTED_KEY.format(url))
        if already_done:
            self._metrics.inc("dedup.skipped_early")
        return not already_done

    def filter_new_urls(self, urls: Iterable[str]) -> List[str]:
        urls = list(urls)
        fresh = [u for u in urls if self.is_new_url(u)]
        skipped = len(urls) - len(fresh)
        if skipped:
            logger.info("DeduplicationService: skipped %d/%d URL(s) already exported", skipped, len(urls))
        self._metrics.inc("dedup.skipped_early_batch", skipped)
        return fresh

    # ── Checkpoint ───────────────────────────────────────────────────

    def mark_exported(self, url: str) -> None:
        self._store.save(_EXPORTED_KEY.format(url), True)

    # ── Run lifecycle ───────────────────────────────────────────────

    def begin_run(self) -> None:
        self._store.save(_RUN_STATE_KEY, True)

    def end_run(self, outcome: RunOutcome, scrape_error_count: int = 0) -> None:
        had_errors = scrape_error_count > 0
        self._store.save(_LAST_RUN_ERRORS_KEY, had_errors)
        self._store.save(_LAST_OUTCOME_KEY, outcome.name)

        if outcome is RunOutcome.COMPLETED and not had_errors:
            self._store.save(_RUN_STATE_KEY, False)
            logger.info("end_run: COMPLETED, no errors — next run can start fresh if you choose to")
        else:
            logger.info(
                "end_run: outcome=%s errors=%d — run_in_progress stays True",
                outcome.name, scrape_error_count,
            )

                
    def mark_checked_empty(self, url: str) -> None:
        """A dealer/listing page was fetched successfully and confirmed to
        have no data (e.g. 'No matching listings found') — NOT a failure,
        NOT an export. Remembering this means we never waste a request
        re-checking it again, in either the main crawl or a retry pass."""
        self._store.save(_CHECKED_EMPTY_KEY.format(url), True)

    def is_checked_empty(self, url: str) -> bool:
        return bool(self._store.load(_CHECKED_EMPTY_KEY.format(url)))

    def previous_run_incomplete(self) -> bool:
        """Informational — True unless the last run explicitly finished clean."""
        return self._store.load(_RUN_STATE_KEY) is not False