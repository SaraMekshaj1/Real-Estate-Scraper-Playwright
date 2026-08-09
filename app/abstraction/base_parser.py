from __future__ import annotations

import abc
from typing import Any, List


class BaseParser(abc.ABC):
    """
    Contract for turning one final (already-fetched) page's HTML into
    zero or more raw record dicts. This is the ONLY place site-specific
    field extraction (CSS selectors, regex, etc.) should live — every
    other service in the pipeline works with plain dicts/Items, never
    with HTML directly.
    """

    @abc.abstractmethod
    def parse(self, raw_content: str, page_url: str) -> List[dict[str, Any]]:
        """Return every record extractable from this page as a list of dicts."""
