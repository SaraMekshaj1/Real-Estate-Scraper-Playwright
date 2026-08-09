# app/utils/retry_policy.py
from __future__ import annotations
import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Awaitable, Callable, ParamSpec, Type, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class RetryExhaustedError(RuntimeError):
    """All retry attempts were consumed without success."""


class CircuitOpenError(RuntimeError):
    """Request blocked — circuit breaker is in OPEN state."""


class RetryableHTTPError(RuntimeError):
    """
    Raised by an HTTP layer to convert a transient HTTP status (429, 500,
    502, 503, 504...) into something the retry/circuit-breaker layer
    understands. Without this conversion, `RetryPolicy.should_retry_status`
    and `RetryPolicy.retryable_status` are dead config — nothing ever
    raises an exception that carries the status back to the retry layer.

    Carries an optional `retry_after` hint (parsed from a Retry-After
    header) so `RetryPolicy.compute_delay` can honor it instead of
    falling back to exponential backoff.
    """

    def __init__(self, status: int, message: str | None = None, retry_after: float | None = None) -> None:
        super().__init__(message or f"Retryable HTTP status {status}")
        self.status = status
        self.retry_after = retry_after


class NonRetryableHTTPError(RuntimeError):
    """
    Raised for a permanent/business HTTP failure (401, 403, 400, 410,
    etc. — anything that isn't 404-special-cased and isn't in
    retryable_status). Deliberately NOT retried and NOT counted toward
    circuit-breaker health: repeated 403s are evidence your request is
    unauthorized, not evidence the dependency is unhealthy.
    """

    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(message or f"Non-retryable HTTP status {status}")
        self.status = status


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP-date). Returns seconds to wait, or None."""
    if not header_value:
        return None
    try:
        return float(header_value)
    except ValueError:
        import email.utils
        try:
            ts = email.utils.parsedate_to_datetime(header_value).timestamp()
            return max(0.0, ts - time.time())
        except Exception:
            return None


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    # Fraction of the computed delay used as the floor for jitter, e.g.
    # 0.2 means "never sleep less than 20% of the backed-off delay."
    # Default 0.0 preserves classic full-jitter (can produce a 0s sleep,
    # i.e. an immediate retry) — for a rate-limited scraper, consider
    # setting this to something like 0.15-0.3 so a "retry" after a 429
    # can't land back-to-back with the original request.
    min_jitter_fraction: float = 0.0
    retryable_exc: tuple[Type[Exception], ...] = field(
        default_factory=lambda: (ConnectionError, TimeoutError, OSError, RetryableHTTPError)
    )
    retryable_status: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )
    non_retryable_status: frozenset[int] = field(
        default_factory=lambda: frozenset({400, 401, 403, 404, 405, 410})
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay must be >= 0, got {self.base_delay}")
        if self.max_delay < 0:
            raise ValueError(f"max_delay must be >= 0, got {self.max_delay}")
        if self.max_delay < self.base_delay:
            raise ValueError(f"max_delay ({self.max_delay}) must be >= base_delay ({self.base_delay})")
        if not 0.0 <= self.min_jitter_fraction <= 1.0:
            raise ValueError(f"min_jitter_fraction must be in [0, 1], got {self.min_jitter_fraction}")

    def compute_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """How many seconds to wait before *attempt* (0-indexed)."""
        if retry_after is not None:
            return max(0.0, retry_after)
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            low = delay * self.min_jitter_fraction
            delay = random.uniform(low, delay)
        return delay

    def should_retry_status(self, status: int) -> bool:
        if status in self.non_retryable_status:
            return False
        return status in self.retryable_status

    def should_retry_exc(self, exc: Exception) -> bool:
        return isinstance(exc, self.retryable_exc)


class CircuitState(Enum):
    CLOSED = auto()     # normal operation
    OPEN = auto()       # blocking requests after too many failures
    HALF_OPEN = auto()  # cooldown passed — let ONE test request through


class CircuitBreaker:
    """
    Three-state circuit breaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).

    Thread/coroutine-safe: all state transitions happen under a
    `threading.Lock`. This is deliberately `threading.Lock`, not
    `asyncio.Lock` — the critical sections here are tiny, synchronous,
    and contain no `await`, so a plain lock works correctly whether this
    breaker is driven from sync worker threads, an asyncio event loop, or
    (if you ever mix them) both. Don't swap this for `asyncio.Lock`
    unless every caller is guaranteed to be on the same event loop.

    HALF_OPEN truly allows exactly one probe in flight at a time: the
    first caller to observe HALF_OPEN claims the single probe slot;
    everyone else is blocked until that probe resolves. If the probe
    succeeds -> CLOSED. If it fails -> OPEN immediately, regardless of
    failure_threshold (a failed probe is definitive: don't wait for N
    more failures to reopen).

    Scoping: create ONE CircuitBreaker per dependency/host and share it
    across all workers hitting that dependency (e.g. one instance owned
    by your `BrowserClient`/`HttpClient`, not one per worker/task).
    Per-worker breakers can each stay under threshold while the
    dependency as a whole is being hammered continuously.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_secs: float = 30.0,
        name: str = "default",
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1, got {failure_threshold}")
        if recovery_secs < 0:
            raise ValueError(f"recovery_secs must be >= 0, got {recovery_secs}")

        self.failure_threshold = failure_threshold
        self.recovery_secs = recovery_secs
        self.name = name

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_ts = 0.0
        self._half_open_probe_in_flight = False

    def _state_locked(self) -> CircuitState:
        """Must be called with self._lock held."""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_ts >= self.recovery_secs:
                logger.info("[CircuitBreaker:%s] OPEN -> HALF_OPEN (probing)", self.name)
                self._state = CircuitState.HALF_OPEN
                self._half_open_probe_in_flight = False
        return self._state

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state_locked()

    @property
    def consecutive_failures(self) -> int:
        """Kept for callers (e.g. BrowserClient's CAPTCHA cooldown math) that
        scale a delay by how many failures have happened in a row."""
        with self._lock:
            return self._failure_count

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._half_open_probe_in_flight = False
            if self._state != CircuitState.CLOSED:
                logger.info("[CircuitBreaker:%s] -> CLOSED", self.name)
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_ts = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # The probe failed — reopen immediately, don't wait for
                # failure_threshold to be reached again.
                logger.warning("[CircuitBreaker:%s] probe failed -> OPEN", self.name)
                self._state = CircuitState.OPEN
                self._half_open_probe_in_flight = False
                return

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "[CircuitBreaker:%s] -> OPEN after %d failures",
                        self.name, self._failure_count,
                    )
                self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        with self._lock:
            s = self._state_locked()
            if s == CircuitState.CLOSED:
                return True
            if s == CircuitState.HALF_OPEN:
                if self._half_open_probe_in_flight:
                    # Someone else already has the one probe slot.
                    return False
                self._half_open_probe_in_flight = True
                return True
            return False  # OPEN


def with_retry(
    policy: RetryPolicy, circuit_breaker: CircuitBreaker | None = None
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator factory for wrapping a SYNC callable with retry + breaker logic."""

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if circuit_breaker and not circuit_breaker.allow_request():
                raise CircuitOpenError(f"Circuit breaker '{circuit_breaker.name}' is OPEN")

            last_exc: Exception | None = None
            for attempt in range(policy.max_attempts):
                try:
                    result = fn(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except Exception as exc:
                    last_exc = exc
                    retry_after = getattr(exc, "retry_after", None)

                    if not policy.should_retry_exc(exc):
                        # Permanent/business failure — not evidence the
                        # dependency is unhealthy, so it does NOT count
                        # toward the circuit breaker, and it's not retried.
                        raise

                    if attempt < policy.max_attempts - 1:
                        delay = policy.compute_delay(attempt, retry_after)
                        logger.warning(
                            "Attempt %d/%d failed for %s — retrying in %.2fs | %s",
                            attempt + 1, policy.max_attempts, fn.__name__, delay, exc,
                        )
                        time.sleep(delay)
                    else:
                        if circuit_breaker:
                            circuit_breaker.record_failure()

            raise RetryExhaustedError(f"All {policy.max_attempts} attempts failed") from last_exc

        return wrapper
    return decorator


def with_async_retry(
    policy: RetryPolicy, circuit_breaker: CircuitBreaker | None = None
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator factory for wrapping an ASYNC callable with retry + breaker logic."""

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if circuit_breaker and not circuit_breaker.allow_request():
                raise CircuitOpenError(f"Circuit breaker '{circuit_breaker.name}' is OPEN")

            last_exc: Exception | None = None
            for attempt in range(policy.max_attempts):
                try:
                    result = await fn(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except Exception as exc:
                    last_exc = exc
                    retry_after = getattr(exc, "retry_after", None)

                    if not policy.should_retry_exc(exc):
                        # Same reasoning as the sync wrapper: permanent/
                        # business failures don't count toward the breaker.
                        raise

                    if attempt < policy.max_attempts - 1:
                        delay = policy.compute_delay(attempt, retry_after)
                        logger.warning(
                            "Async attempt %d/%d failed for %s — retrying in %.2fs | %s",
                            attempt + 1, policy.max_attempts, fn.__name__, delay, exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        if circuit_breaker:
                            circuit_breaker.record_failure()

            raise RetryExhaustedError(f"All {policy.max_attempts} attempts failed") from last_exc

        return wrapper
    return decorator