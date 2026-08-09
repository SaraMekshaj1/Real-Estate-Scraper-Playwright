from __future__ import annotations
import asyncio
import time
class RateLimiter:
    """
    Token-bucket rate limiter shared across every concurrent request.
    Enforces "at most `rate` requests per `period` seconds" GLOBALLY —
    tasks never guess timing themselves; they all call acquire() and
    this is the one place that decides when a request is allowed to
    fire. Concurrency (how many requests run at once) and rate (how
    many per minute) are separate dials — this is the rate dial, and
    it's the one that actually matters once a site enforces an RPM cap.

    Bucket starts full (burst of `rate` allowed immediately), then
    refills continuously at rate/period tokens per second.
    """

    def __init__(self, rate: int, period: float = 60.0) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = rate
        self._period = period
        self._tokens = float(rate)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / self._period))

                if self._tokens >= 1:
                    self._tokens -= 1
                    return

                wait = (1 - self._tokens) * (self._period / self._rate)
                await asyncio.sleep(wait)
