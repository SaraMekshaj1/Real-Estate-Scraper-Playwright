from __future__ import annotations
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from app.abstraction.base_link_extractor import BaseLinkExtractor
from app.exceptions.scraper_exceptions import ParsingError
from app.utils.url_utils import canonicalize_url_safe
import logging
logger = logging.getLogger(__name__)


class PropertiesLinksExtractor(BaseLinkExtractor):
    """
    Listing page here has no separate 'card' wrapper — the anchor
    itself (`a.h-full`) is both the card and the link, e.g.:
        <a class="h-full" href="/property/123">Property Name</a>
    """

    def __init__(
        self,
        link_selector: str = "a.h-full",
        parser_backend: str = "lxml",
    ) -> None:
        self._link_selector = link_selector
        self._backend = parser_backend

    def extract(self, raw_content: str, page_url: str) -> List[Tuple[str, Dict[str, Any]]]:
        try:
            soup = BeautifulSoup(raw_content, self._backend)
        except Exception as exc:  # noqa: BLE001
            raise ParsingError(f"Failed to build soup: {exc}") from exc

        results: List[Tuple[str, Dict[str, Any]]] = []
        seen: set[str] = set()

        for a in soup.select(self._link_selector):
            href = a.get("href")
            if not href:
                continue

            item_url = canonicalize_url_safe(urljoin(page_url, href))
            if item_url in seen:
                continue
            seen.add(item_url)

            context = {"name": a.get_text(strip=True)}
            results.append((item_url, context))

        if not results:
            logger.warning(
                "extract: no links found on %s — selector '%s' may be stale "
                "or the page structure has changed",
                page_url, self._link_selector,
            )

        return results