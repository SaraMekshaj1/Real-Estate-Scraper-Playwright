from __future__ import annotations

from app.abstraction.base_paginator import BasePaginator


class NoOpPaginator(BasePaginator):
    """
    Used when the seed page already contains everything needed to find
    every link (e.g. an embedded JSON blob, or a single directory page)
    — there is no "next page" concept. Crawler.crawl() will yield
    exactly the seed URL and then stop, since has_next always reports
    False.
    """

    def has_next(self, raw_content: str) -> bool:
        return False

    def next_url(self, current_url: str, raw_content: str) -> str:
        raise NotImplementedError("NoOpPaginator never has a next page.")
