from __future__ import annotations
import asyncio
import logging
import random
from typing import Any, Callable, Mapping, Optional
from app.abstraction.base_client import BaseClient
from app.config.settings import Settings
from app.exceptions.scraper_exceptions import CaptchaDetectedError, ClientError, PageNotFoundError, SoftBlockError
from app.utils.retry_policy import CircuitBreaker, CircuitOpenError, RetryPolicy, parse_retry_after

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

_BROWSER_DEAD_SIGNALS = (
    "Target page, context or browser has been closed",
    "Browser has been closed",
    "Connection closed",
    "Target closed",
)

_CAPTCHA_MARKERS = (
    "hcaptcha-challenge",
    "are you a real person",
    "verify you are human",
    "please verify you are a human",
    "checking your browser before accessing",
    "g-recaptcha-response",   # the challenge iframe token field, not the loader script
    "cf-challenge",
    "attention required! | cloudflare",
)


class BrowserClient(BaseClient):
    """
    Playwright-based client: fetches pages with a real headless
    Chromium instead of raw HTTP. Only switch to this mode if the
    target site needs JS rendering or actively blocks plain HTTP
    clients — it's significantly slower and heavier (each concurrent
    request is a real browser page, not a lightweight coroutine).

    Built-in resilience:
      - RetryPolicy (backoff+jitter) + CircuitBreaker (opens after
        sustained REAL failures — never on 404s or other 4xx business
        failures, which are triaged separately and don't count as
        evidence the dependency itself is unhealthy).
      - HTTP status handling is routed through
        `RetryPolicy.should_retry_status` instead of a hardcoded status
        list, so the policy's retryable/non-retryable sets are the
        actual source of truth for what gets retried here.
      - Adaptive delay that widens automatically after a rate-limit
        signal (429/503) and slowly recovers on success.
      - CAPTCHA-page detection via a marker scan.
      - Soft-block detection via an optional content_validator: a page
        can load fine (200, no CAPTCHA) but be silently missing the
        data you came for. When that happens, the client ROTATES its
        session (fresh cookies + fingerprint, same browser process)
        rather than just retrying with the same, likely-flagged,
        session.

    IMPORTANT — scoping: one BrowserClient instance (and therefore one
    CircuitBreaker instance) should be shared across all workers hitting
    the same target host. Don't construct a fresh BrowserClient per
    worker/task — that gives each worker its own breaker, and workers
    can each individually stay under threshold while collectively still
    hammering a dead target.
    """

    def __init__(
        self,
        settings: Settings,
        retry_policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self._settings = settings
        self._retry_policy = retry_policy or RetryPolicy()
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._delay_multiplier = 1.0
        self._warmed_up = False
        self._request_count = 0
        self._playwright = None
        self._browser = None
        self._context = None
        self._launch_lock = asyncio.Lock()

    # ── Playwright setup ──────────────────────────────────────────────

    async def _launch_browser_if_needed(self) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._settings.browser_headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )

    async def _new_context(self):
        ua = random.choice(_USER_AGENTS) if self._settings.rotate_user_agents else _USER_AGENTS[0]
        context = await self._browser.new_context(
            user_agent=ua,
            viewport=random.choice(_VIEWPORTS),
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            "Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });"
        )
        return context

    async def _get_context(self):
        """
        Returns a live browser context, creating/relaunching it under
        the lock if needed. ALWAYS go through this method to get a
        context right before using it (never read self._context
        directly and hold onto it across an `await`) — that's what
        keeps concurrent workers from ever seeing a half-swapped or
        None context mid-request.
        """
        async with self._launch_lock:
            if self._context is None:
                await self._launch_browser_if_needed()
                self._context = await self._new_context()
                logger.info("Playwright browser launched (headless=%s)", self._settings.browser_headless)
            return self._context

    async def _ensure_browser(self) -> None:
        await self._get_context()

    async def _restart_browser(self) -> None:
        """
        Full teardown + relaunch — used when the browser PROCESS itself
        has died. Lock-guarded so concurrent workers that all hit a
        dead-browser error at once don't each tear down/relaunch on top
        of each other (that double-teardown is what previously produced
        "'NoneType' object has no attribute 'new_page'").
        """
        async with self._launch_lock:
            if self._browser is None:
                # Another worker already restarted while we were
                # waiting on the lock — nothing more to do.
                return
            logger.info("Restarting Playwright browser (process appears dead)...")
            context, browser, playwright = self._context, self._browser, self._playwright
            self._context = self._browser = self._playwright = None
            self._warmed_up = False
            for resource, closer in ((context, "close"), (browser, "close"), (playwright, "stop")):
                if resource is None:
                    continue
                try:
                    await getattr(resource, closer)()
                except Exception as exc:
                    logger.debug("Cleanup during restart (non-fatal): %s", exc)
            await self._launch_browser_if_needed()
            self._context = await self._new_context()

    async def _rotate_session(self) -> None:
        """
        Fresh cookies + fingerprint, SAME browser process — much
        cheaper than a full restart, and this is what actually fixes a
        per-session soft block.

        IMPORTANT: the old context is NOT closed immediately. Other
        workers may still have pages open against it — closing it out
        from under them is exactly what previously caused unrelated
        workers to fail with "Target page, context or browser has been
        closed". Instead, new work switches to the new context right
        away, and the old one is closed after a grace period long
        enough for any in-flight request (bounded by request_timeout)
        to finish naturally.
        """
        async with self._launch_lock:
            old_context = self._context
            await self._launch_browser_if_needed()
            self._context = await self._new_context()
        logger.info("Session rotated (new context) after %d request(s)", self._request_count)
        if old_context is not None:
            asyncio.create_task(self._close_context_later(old_context))

    async def _close_context_later(self, context, delay: float = 35.0) -> None:
        await asyncio.sleep(delay)
        try:
            await context.close()
        except Exception as exc:
            logger.debug("Delayed context close (non-fatal): %s", exc)

    # ── Adaptive delay ────────────────────────────────────────────────

    async def _adaptive_delay(self) -> None:
        lo, hi = self._settings.request_delay_min_secs, self._settings.request_delay_max_secs
        base = max(lo, random.gauss(mu=(lo + hi) / 2, sigma=(hi - lo) / 4))
        delay = base * self._delay_multiplier
        logger.debug("Delay: %.2fs (multiplier=%.1fx)", delay, self._delay_multiplier)
        await asyncio.sleep(delay)

    def _on_success(self) -> None:
        self._circuit_breaker.record_success()
        if self._delay_multiplier > 1.0:
            self._delay_multiplier = max(1.0, self._delay_multiplier * 0.9)

    def _on_rate_limited(self) -> None:
        self._circuit_breaker.record_failure()
        self._delay_multiplier = min(20.0, self._delay_multiplier * 2.0)
        logger.warning("Rate limited — delay multiplier now %.1fx", self._delay_multiplier)

    # ── Session warmup ────────────────────────────────────────────────

    async def warmup(self, base_url: str) -> None:
        """Visit the homepage once before real scraping starts — establishes
        a session the way a real visitor's browser would, rather than
        landing cold on a deep page."""
        if self._warmed_up:
            return
        context = await self._get_context()
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"
        logger.info("Session warmup: visiting %s", homepage)
        page = await context.new_page()
        try:
            await page.goto(homepage, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 3.0))
        except Exception as exc:
            logger.warning("Warmup failed (non-fatal): %s", exc)
        finally:
            self._warmed_up = True
            try:
                await page.close()
            except Exception:
                pass

    @staticmethod
    def _looks_like_captcha(html: str) -> bool:
        lowered = html[:3000].lower()
        return any(marker in lowered for marker in _CAPTCHA_MARKERS)

    # ── Core fetch ────────────────────────────────────────────────────

    async def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        referer: Optional[str] = None,
        content_validator: Optional[Callable[[str], bool]] = None,
    ) -> str:
        max_attempts = self._settings.retry_max_attempts
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            if not await self._wait_for_circuit(url):
                raise CircuitOpenError(f"Circuit breaker is OPEN — aborting request to {url}")
            await self._adaptive_delay()

            # Fetched right before use, not cached earlier in the loop —
            # if another worker rotated/restarted between attempts, this
            # always gets the CURRENT live context, never a stale one.
            context = await self._get_context()

            page = None
            try:
                page = await context.new_page()
                if referer:
                    await page.set_extra_http_headers({"Referer": referer})

                response = await page.goto(url, wait_until="networkidle", timeout=30_000)
                if response is None:
                    raise RuntimeError(f"No response for {url}")

                status = response.status

                # 404 is special-cased ahead of the generic retry check:
                # it's terminal (no point retrying) but distinct from a
                # true "not found, and also unhealthy" scenario.
                if status == 404:
                    raise PageNotFoundError(f"HTTP 404 for {url}")

                if self._retry_policy.should_retry_status(status):
                    if status in (429, 503):
                        # Rate-limit signal: widen the adaptive delay and
                        # prefer the server's own Retry-After if present.
                        self._on_rate_limited()
                        header_delay = parse_retry_after(response.headers.get("retry-after"))
                        retry_after = self._retry_policy.compute_delay(
                            attempt - 1, retry_after=header_delay if header_delay is not None else 10.0
                        )
                    else:
                        # 500/502/504 — a real infra-side failure, worth
                        # counting toward the circuit breaker even though
                        # it arrived as a status code, not an exception.
                        self._circuit_breaker.record_failure()
                        retry_after = self._retry_policy.compute_delay(attempt - 1)

                    logger.warning(
                        "HTTP %d — sleeping %.0fs (attempt %d/%d)", status, retry_after, attempt, max_attempts
                    )
                    await page.close(); page = None
                    await asyncio.sleep(retry_after)
                    continue

                if status >= 400:
                    # Business/permanent failure (401, 403, 400, 410, or
                    # any other status not classified as retryable). This
                    # is NOT evidence the remote service is unhealthy, so
                    # it deliberately does not touch the circuit breaker.
                    raise RuntimeError(f"HTTP {status} for {url}")

                html = await page.content()

                if self._looks_like_captcha(html):
                    self._on_rate_limited()
                    cooldown = self._settings.captcha_cooldown_seconds * self._circuit_breaker.consecutive_failures
                    logger.error("Bot-check page at %s — cooling down %.0fs", url, cooldown)
                    await page.close(); page = None
                    await asyncio.sleep(cooldown)
                    raise CaptchaDetectedError(f"Bot-check page served for {url}")

                if content_validator is not None and not content_validator(html):
                    logger.warning(
                        "Expected content missing at %s (attempt %d/%d) — likely a soft "
                        "block. Rotating session.", url, attempt, max_attempts,
                    )
                    await page.close(); page = None
                    await self._rotate_session()
                    if attempt < max_attempts:
                        await asyncio.sleep(self._retry_policy.compute_delay(attempt - 1))
                        continue
                    raise SoftBlockError(f"Expected content still missing at {url} after {max_attempts} attempts")

                self._on_success()
                self._request_count += 1
                if self._settings.session_rotate_after and self._request_count % self._settings.session_rotate_after == 0:
                    await self._rotate_session()

                return html

            except asyncio.CancelledError:
                raise
            except CircuitOpenError:
                raise
            except (PageNotFoundError, SoftBlockError):
                raise
            except Exception as exc:
                last_exc = exc
                if any(sig in str(exc) for sig in _BROWSER_DEAD_SIGNALS):
                    logger.warning("Browser appears dead (attempt %d/%d): %s — restarting", attempt, max_attempts, exc)
                    await self._restart_browser()
                    await asyncio.sleep(3.0)
                    continue
                self._circuit_breaker.record_failure()
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, max_attempts, url, exc)
                if attempt < max_attempts:
                    await asyncio.sleep(self._retry_policy.compute_delay(attempt - 1))
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

        raise ClientError(f"All {max_attempts} attempts failed for {url}") from last_exc

    async def close(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = self._browser = self._playwright = None
        self._warmed_up = False
        for resource, closer in ((context, "close"), (browser, "close"), (playwright, "stop")):
            if resource is None:
                continue
            try:
                await getattr(resource, closer)()
            except Exception as exc:
                logger.debug("Cleanup on close (non-fatal): %s", exc)
        logger.info("Playwright browser closed")

    async def _wait_for_circuit(self, url: str) -> bool:
        """
        If the breaker is OPEN, don't fail instantly — wait up to one
        recovery window, checking once a second, for it to move to
        HALF_OPEN/CLOSED again. This is what lets a short blip (a few
        seconds of dropped internet) get ridden out quietly instead of
        instantly failing every request still left in the queue.

        Returns True once a request is allowed through, False if still
        blocked after the wait — at which point the caller should treat
        this as a real, sustained failure (record it, move on).
        """
        if self._circuit_breaker.allow_request():
            return True

        max_wait = self._circuit_breaker.recovery_secs + 2.0  # small buffer past the breaker's own timer
        logger.warning("Circuit breaker OPEN for %s — waiting up to %.0fs for recovery", url, max_wait)
        waited = 0.0
        while waited < max_wait:
            await asyncio.sleep(1.0)
            waited += 1.0
            if self._circuit_breaker.allow_request():
                logger.info("Circuit breaker recovered after %.0fs — resuming %s", waited, url)
                return True

        logger.warning("Circuit breaker still OPEN after %.0fs — giving up on %s for now", waited, url)
        return False