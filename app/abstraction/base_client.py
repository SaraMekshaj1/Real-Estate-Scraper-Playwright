from __future__ import annotations
import abc
from typing import Any, Callable, Mapping, Optional

class BaseClient(abc.ABC):
    """
    Contract for anything that fetches raw content over HTTP(S).

    Implementations own connection/session lifecycle, retries, rate
    limiting, and any anti-bot-detection countermeasures. Callers never
    see aiohttp/Playwright-specific types — they only ever see plain
    text back. This is what lets you swap a raw-HTTP client for a
    full-browser client (or vice versa) without touching anything else
    in the pipeline (Crawler, CrawlService, ScrapingService, ...).

    `content_validator`, if given, is called with the fetched HTML and
    should return True if the page contains what you actually expected
    (not just "did the HTTP request succeed"). This is how a SOFT block
    — a 200 response with the real content quietly missing — gets
    caught. Implementations that support it should raise
    SoftBlockError (see exceptions) when the validator returns False.
    """

    @abc.abstractmethod
    async def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        referer: Optional[str] = None,
        content_validator: Optional[Callable[[str], bool]] = None,
    ) -> str:
        """Fetch *url* and return the raw/rendered page body as text."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release underlying connections/sessions/browser resources."""

    async def __aenter__(self) -> "BaseClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
