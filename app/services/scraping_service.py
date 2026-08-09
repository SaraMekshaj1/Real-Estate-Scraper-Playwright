from __future__ import annotations
import logging
from typing import Any, Dict, Iterator, Optional
from app.abstraction.base_mapper import BaseMapper
from app.abstraction.base_normalizer import BaseNormalizer
from app.abstraction.base_parser import BaseParser
from app.abstraction.base_validator import BaseValidator
from app.exceptions.scraper_exceptions import MappingError, ParsingError, ValidationError


class ScrapingService:
    """
    Parses one page's raw HTML into validated Items: parse -> merge
    context -> normalize -> map -> validate.

    `context` is data the listing page already knew about this page
    before it was fetched (e.g. an id/name) — it's merged into every
    record parsed from the page, taking priority over anything the
    parser produced under the same key (the earlier-known source is
    treated as authoritative for those fields).

    Deliberately kept SYNCHRONOUS: parsing is (usually) light CPU work,
    and running it inline avoids the pickling overhead a process pool
    would add for a small parse. If your project's parsing genuinely
    becomes the bottleneck (huge pages, heavy regex/XPath), that's the
    one thing worth offloading — profile before assuming it's needed.
    """

    def __init__(
        self,
        parser: BaseParser,
        normalizers: Dict[str, BaseNormalizer],
        mapper: BaseMapper,
        validator: BaseValidator,
        default_normalizer: Optional[BaseNormalizer] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._parser = parser
        self._normalizers = normalizers
        self._mapper = mapper
        self._validator = validator
        self._default_normalizer = default_normalizer
        self._logger = logger or logging.getLogger(__name__)

    def process_page(
        self,
        page_url: str,
        raw_content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Any]:
        try:
            raw_records = self._parser.parse(raw_content, page_url)
        except ParsingError as exc:
            self._logger.warning("Skipping page %s — parse failed: %s", page_url, exc)
            return

        self._logger.debug("Parsed %d record(s) from %s", len(raw_records), page_url)

        yielded = 0
        for raw in raw_records:
            if context:
                raw = {**raw, **context}
            try:
                normalized = self._normalize_record(raw)
                item = self._mapper.map(normalized)
                self._validator.validate(item)
            except (MappingError, ValidationError) as exc:
                self._logger.warning("Skipping record: %s", exc)
                continue
            yielded += 1
            yield item

        self._logger.info("Page %s -> %d item(s)", page_url, yielded)

    def _normalize_record(self, raw: dict) -> dict:
        result = {}
        for key, value in raw.items():
            normalizer = self._normalizers.get(key, self._default_normalizer)
            result[key] = normalizer.normalize(value) if normalizer else value
        return result
