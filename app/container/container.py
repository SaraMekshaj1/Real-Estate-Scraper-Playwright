from __future__ import annotations
import logging
from typing import Callable, Dict, List, Optional
from app.abstraction.base_client import BaseClient
from app.abstraction.base_exporter import BaseExporter
from app.abstraction.base_normalizer import BaseNormalizer
from app.client.http_client import AsyncHttpClient
from app.client.browser_client import BrowserClient
from app.client.rate_limiter import RateLimiter
from app.config.settings import Settings
from app.crawler.crawler import Crawler
from app.exceptions.scraper_exceptions import ConfigError
from app.exporters.csv_exporter import CSVExporter
from app.exporters.jsonl_exporter import JSONLExporter
from app.mappers.item_mapper import PropertyMapper
from app.normalizers.field_normalizer import TextNormalizer, PriceNormalizer, NumberNormalizer,StatusNormalizer,YesNoNormalizer,CleanTextNormalizer
from app.pagination.next_page import NextPagePaginator
# ADAPT PER PROJECT: swap these three imports for your site-specific
from app.abstraction.base_link_extractor import BaseLinkExtractor
from app.pagination.next_page import NextPagePaginator
# ADAPT PER PROJECT: swap these three imports for your site-specific
# implementations. Everything else in this file (and every other file
# in app/) stays the same.
from app.parsers.example_link_extractor import PropertiesLinksExtractor
from app.parsers.example_parser import PropertyParser
from app.services.crawl_service import CrawlService
from app.services.export_service import ExportService
from app.services.scraping_service import ScrapingService
from app.storage.in_memory_storage import InMemoryStorage
from app.utils.logger import setup_logger, Metrics
from app.validators.item_validator import ItemValidator
from monitoring.run_monitor import RunMonitor
from monitoring.scrape_statistics import ScrapeStatistics
from app.abstraction.base_checkpoint_store import BaseCheckpointStore
from app.storage.checkpoint_store import JsonCheckpointStore
from app.services.deduplication_service import DeduplicationService
from app.storage.failed_url_store import FailedUrlStore

"""
Composition root: the ONLY place in the codebase that knows how to
build concrete implementations. Every other class receives its
dependencies through its constructor (DIP) — nothing else calls a
concrete class's constructor directly.

TO ADAPT THIS TO A NEW PROJECT:
  1. Swap the three imports above (link_extractor / detail_link_extractor
     / parser) for site-specific implementations.
  2. Update `link_extractor()`, `product_picker_link_extractor()` (or
     delete it if you don't need a 3rd hop), and `parser()` below to
     instantiate them.
  3. Update `Item`/`ItemMapper` fields to match (see app/models/item.py,
     app/mappers/item_mapper.py).
  4. Set `required_fields` in `validator()` to whatever makes a record
     actually useful for this project.
  5. Set `detail_content_validator()` to a marker that's present on a
     real, fully-loaded detail page (used for soft-block detection).
  6. Set BASE_URL (and CLIENT_MODE, if switching to "browser") in .env.

Nothing else needs to change.
"""

class Container:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.metrics = Metrics()
        self.logger: logging.Logger = setup_logger(
            name="scraper",
            level=self.settings.log_level,
            log_format=self.settings.log_format,
            log_file=self.settings.log_file or None,
            extra_fields={"base_url": self.settings.base_url},
        )
        # Cached singletons — anything with meaningful lifecycle/state
        # should be built once per run, not once per injection point.
        self._client: Optional[BaseClient] = None
        self._storage: Optional[InMemoryStorage] = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._checkpoint_store: Optional[BaseCheckpointStore] = None
        self._dedup: Optional[DeduplicationService] = None
        self._failed_url_store: Optional[FailedUrlStore] = None

    # --- infra (mostly stays the same across projects) ------------------

    def rate_limiter(self) -> Optional[RateLimiter]:
        """HTTP mode only. None disables rate limiting (concurrency cap
        is the only throttle in that case)."""
        if self.settings.rate_limit_rpm <= 0:
            return None
        if self._rate_limiter is None:
            self._rate_limiter = RateLimiter(self.settings.rate_limit_rpm, period=60.0)
        return self._rate_limiter

    #a factory 
    def client(self) -> BaseClient:
        """
        Picks the transport based on Settings.client_mode:
          "http"    -> AsyncHttpClient (aiohttp) — fast, cheap, DEFAULT.
                       Try this first on every new project.
          "browser" -> BrowserClient (Playwright) — slower, heavier,
                       renders like a real browser. Only switch to this
                       if the site needs JS rendering or actively
                       blocks plain HTTP clients.
        """
        if self._client is None:
            mode = self.settings.client_mode.lower()
            if mode == "http":
                self._client = AsyncHttpClient(self.settings, self.logger, rate_limiter=self.rate_limiter())
            elif mode == "browser":
                self._client = BrowserClient(self.settings)
            else:
                raise ConfigError(f"Unknown CLIENT_MODE={mode!r} — expected 'http' or 'browser'")
        return self._client

    def exporters(self) -> List[BaseExporter]:
        return [
            CSVExporter(self.settings, logger=self.logger),
            JSONLExporter(self.settings, logger=self.logger),
        ]

    def storage(self) -> InMemoryStorage:
        if self._storage is None:
            self._storage = InMemoryStorage()
        return self._storage

    # --- site-specific (ADAPT PER PROJECT) -------------------------------

    def link_extractor(self) -> PropertiesLinksExtractor:
        return PropertiesLinksExtractor()

    def detail_link_extractor(self) -> Optional[BaseLinkExtractor]:
        """2-hop project — a.h-full already points at the final property
        page, no third hop needed."""
        return None

    def parser(self) -> PropertyParser:
        return PropertyParser()

    def mapper(self) -> PropertyMapper:
        return PropertyMapper()


    def normalizers(self) -> Dict[str, BaseNormalizer]:
        return {
            "price_raw":          PriceNormalizer(),
            "total_area":         NumberNormalizer(),
            "internal_area":      NumberNormalizer(),
            "number_of_bedrooms": NumberNormalizer(),
            "floor":              NumberNormalizer(),
            "number_of_toilets":  NumberNormalizer(),
            "statusi":            StatusNormalizer(),
            "mobilimi":           YesNoNormalizer(),
            "ka_hipoteke":        YesNoNormalizer(),
            "ashensor":           YesNoNormalizer(),
            "title":              CleanTextNormalizer(),
            "location":           CleanTextNormalizer(),
            "description":        CleanTextNormalizer(),
            "lloji":              CleanTextNormalizer(),
            "karakteristikat":    CleanTextNormalizer(),
        }

    def default_normalizer(self) -> BaseNormalizer:
        return TextNormalizer()


    def validator(self) -> ItemValidator:
        return ItemValidator(required_fields=("property_id", "url", "title"))

    def detail_content_validator(self) -> Optional[Callable[[str], bool]]:
        """Unused in a 2-hop pipeline — only referenced by CrawlService
        inside the detail_link_extractor branch, which is None here."""
        return None

    def next_page_paginator(self):
        """NoOpPaginator for a single seed page (default). Swap for
        Paginator(self.settings.next_page_selector) if the site has
        real ?page=N / "next link" pagination."""
        return NextPagePaginator(self.settings.next_page_selector)

    def crawler(self) -> Crawler:
        return Crawler(self.client(), self.next_page_paginator(), self.settings.max_pages, self.logger)

    def detail_content_validator(self) -> Callable[[str], bool]:
        # Cheap substring check — the contact-info block on a valid
        # product page always renders with this container class.
        marker = "elt_contact_info_table"
        return lambda html: marker in html

    def checkpoint_store(self) -> BaseCheckpointStore:
        if self._checkpoint_store is None:
            self._checkpoint_store = JsonCheckpointStore(self.settings.checkpoint_path)
        return self._checkpoint_store

    def deduplication_service(self) -> Optional[DeduplicationService]:
        if not self.settings.enable_resume:
            return None
        if self._dedup is None:
            self._dedup = DeduplicationService(self.checkpoint_store(), self.metrics)
        return self._dedup

    def failed_url_store(self) -> FailedUrlStore:
        if self._failed_url_store is None:
            self._failed_url_store = FailedUrlStore(self.settings.failed_urls_path)
        return self._failed_url_store


    # --- services --------------------------------------------------------

    def crawl_service(self) -> CrawlService:
        return CrawlService(
            client=self.client(),
            crawler=self.crawler(),
            link_extractor=self.link_extractor(),
            detail_link_extractor=self.detail_link_extractor(),
            detail_content_validator=self.detail_content_validator(),
            max_workers=self.settings.max_concurrent_requests,
            logger=self.logger,
            dedup=self.deduplication_service(),
            failed_url_store=self.failed_url_store(),
        )

    def scraping_service(self) -> ScrapingService:
        return ScrapingService(
            parser=self.parser(),
            normalizers=self.normalizers(),
            mapper=self.mapper(),
            validator=self.validator(),
            default_normalizer=self.default_normalizer(),
            logger=self.logger,
        )

    def export_service(self) -> ExportService:
        return ExportService(self.exporters(), self.logger)

    # --- engine ---------------------------------------------------------

    def scraper_engine(self):
        from app.orchestration.scraper_engine import ScraperEngine
        return ScraperEngine(
            crawl_service=self.crawl_service(),
            scraping_service=self.scraping_service(),
            export_service=self.export_service(),
            statistics=ScrapeStatistics(),
            monitor=RunMonitor(self.logger),
            settings=self.settings,
            logger=self.logger,
            dedup=self.deduplication_service(),
        )
