from __future__ import annotations
from typing import Any, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from app.abstraction.base_paginator import BasePaginator


class NextPagePaginator(BasePaginator):
    """
    ADAPT PER PROJECT (only if the site uses this style of pagination):
    finds a "next page" link via a CSS selector (e.g. "li.next a",
    "a[rel=next]"). Set `next_page_selector` in Settings/.env.
    """

    def __init__(self, next_page_selector: str, parser_backend: str = "lxml") -> None:
        self._selector = next_page_selector
        self._backend = parser_backend

    def has_next(self, current_page: Any) -> bool:
        return self._find_next_href(current_page) is not None

    def next_url(self, current_url: str, current_page: Any) -> Optional[str]:
        href = self._find_next_href(current_page)
        if href is None:
            return None
        return urljoin(current_url, href)

    def _find_next_href(self, current_page: Any) -> Optional[str]:
        soup = BeautifulSoup(str(current_page), self._backend)
        link = soup.select_one(self._selector)
        if not link or not link.get("href"):
            return None
        return link["href"]
