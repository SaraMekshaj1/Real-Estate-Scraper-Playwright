from __future__ import annotations

import abc
from typing import Any, Dict, List, Tuple


class BaseLinkExtractor(abc.ABC):
    """
    Contract for pulling (url, context) pairs out of a page's HTML.

    `context` is anything already known about that URL from the page it
    was found on (e.g. an id/name embedded in a listing row) — it rides
    forward through the crawl chain and gets merged into the final
    scraped record, rather than being re-extracted from a later page.

    Every site-specific extractor (link_extractor AND, optionally, a
    second detail_link_extractor for multi-hop chains) implements this
    same contract — that symmetry is what lets CrawlService support an
    arbitrary number of hops without any special-casing.
    """

    @abc.abstractmethod
    def extract(self, raw_content: str, page_url: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Return every (url, context) pair discoverable on this page."""
