from __future__ import annotations
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from app.abstraction.base_link_extractor import BaseLinkExtractor
from app.exceptions.scraper_exceptions import ParsingError


#This will not be used 

class ExampleDetailLinkExtractor(BaseLinkExtractor):
    """
    OPTIONAL — only needed for a 3-HOP project (listing page -> an
    intermediate page that doesn't reliably have every field -> pick
    ONE link off THAT page -> the page that actually has full data).

    If your project only needs 2 hops (listing page -> detail page,
    done), delete this file and pass detail_link_extractor=None in
    container.py.

    This example always picks the FIRST matching link on the
    intermediate page. If there's nothing to pick, returns []
    (CrawlService logs a warning and skips that item — it simply isn't
    reachable via this route).
    """

    def __init__(self, item_selector: str = "div.item-header a", parser_backend: str = "lxml") -> None:
        self._item_selector = item_selector
        self._backend = parser_backend

    def extract(self, raw_content: str, page_url: str) -> List[Tuple[str, Dict[str, Any]]]:
        try:
            soup = BeautifulSoup(raw_content, self._backend)
        except Exception as exc:  # noqa: BLE001
            raise ParsingError(f"Failed to build soup: {exc}") from exc

        node = soup.select_one(self._item_selector)
        if node is None or not node.get("href"):
            return []

        return [(urljoin(page_url, node["href"]), {})]
