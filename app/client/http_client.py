from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Mapping, Optional

import aiohttp

from app.abstraction.base_client import BaseClient
from app.client.rate_limiter import RateLimiter
from app.config.settings import Settings
from app.exceptions.scraper_exceptions import CaptchaDetectedError, ClientError, PageNotFoundError, SoftBlockError


class AsyncHttpClient(BaseClient):
    """
    Generic aiohttp-based HTTP client. Use this by default — try it
    FIRST on every new project before reaching for BrowserClient. Fast,
    cheap, low resource use; fine for any site where the data is in the
    raw page source and there's no aggressive bot-detection.

    Handles:
      - Connection pooling via a shared TCPConnector.
      - Manual retries with exponential backoff (aiohttp has no
        urllib3-style Retry built in).
      - Optional global rate limiting (RateLimiter), independent of the
        concurrency cap (see max_concurrent_requests).
      - CAPTCHA-page detection via a simple marker scan.
      - Soft-block detection via an optional content_validator — a 200
        response that's missing the data you actually came for.

    No project-specific logic lives here beyond the generic CAPTCHA
    marker list — this class should stay the same across projects.
    """

    _CAPTCHA_MARKERS = (
        "hcaptcha",
        "are you a real person",
        "verify your identity",
        "recaptcha",
        "checking your browser",
    )

    def __init__(
        self,
        settings: Settings,
        logger: Optional[logging.Logger] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._settings = settings
        self._logger = logger or logging.getLogger(__name__)
        self._rate_limiter = rate_limiter
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self._settings.max_concurrent_requests,
                ssl=self._settings.verify_ssl,
            )
            timeout = aiohttp.ClientTimeout(total=self._settings.request_timeout)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "User-Agent": self._settings.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    @classmethod
    def _looks_like_captcha(cls, text: str) -> bool:
        lowered = text[:3000].lower()
        return any(marker in lowered for marker in cls._CAPTCHA_MARKERS)

    async def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        referer: Optional[str] = None,
        content_validator: Optional[Callable[[str], bool]] = None,
    ) -> str:
        session = await self._ensure_session()
        attempts = self._settings.retry_max_attempts
        last_exc: Optional[BaseException] = None

        req_headers = dict(headers or {})
        if referer:
            req_headers.setdefault("Referer", referer)

        for attempt in range(attempts):
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()

            try:
                async with self._semaphore:
                    async with session.get(url, params=params, headers=req_headers) as response:
                        if response.status == 404:
                            raise PageNotFoundError(f"HTTP 404 for {url}")
                        if response.status in (429, 500, 502, 503, 504):
                            raise ClientError(f"GET {url} returned transient status {response.status}")
                        response.raise_for_status()
                        text = await response.text()

                if self._looks_like_captcha(text):
                    raise CaptchaDetectedError(f"Bot-check page served for {url}")

                if content_validator is not None and not content_validator(text):
                    raise SoftBlockError(f"Expected content missing at {url}")

                self._logger.debug("Fetched %s (%s bytes)", url, len(text))
                return text

            except PageNotFoundError:
                raise  # never retried, never a "failure"

            except CaptchaDetectedError:
                cooldown = self._settings.captcha_cooldown_seconds
                self._logger.error("Bot-check page at %s — cooling down %.0fs", url, cooldown)
                await asyncio.sleep(cooldown)
                last_exc = CaptchaDetectedError(f"Bot-check page served for {url}")
                if attempt < attempts - 1:
                    continue
                raise

            except SoftBlockError as exc:
                self._logger.warning("Soft block detected at %s (attempt %d/%d)", url, attempt + 1, attempts)
                last_exc = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(self._settings.captcha_cooldown_seconds / 2)
                    continue
                raise

            except (aiohttp.ClientError, ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    backoff = min(30.0, 2.0 * (2 ** attempt))
                    self._logger.debug("Retrying %s after error (%s): sleeping %.2fs", url, exc, backoff)
                    await asyncio.sleep(backoff)
                    continue
                break

        raise ClientError(f"GET {url} failed after {attempts} attempt(s): {last_exc}") from last_exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
