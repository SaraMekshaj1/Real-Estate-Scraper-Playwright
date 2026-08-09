from __future__ import annotations
import logging
import time
from typing import Optional
from app.utils.logger import Metrics


class RunMonitor:
    """Times a run and logs a summary at the end. Extend this to push
    metrics somewhere external (a dashboard, Slack webhook, etc.) if a
    project needs it — kept minimal here on purpose."""

    def __init__(self, logger: Optional[logging.Logger] = None, metrics: Optional[Metrics] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics
        self._started_at: Optional[float] = None

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._logger.info("Run started.")

    def finish(self, scraped: int, expected: int = 0) -> None:
        elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
        if expected:
            self._logger.info(
                "Run finished: %d/%d item(s) in %.1fs (%.1f items/min)",
                scraped, expected, elapsed, (scraped / elapsed * 60) if elapsed else 0,
            )
        else:
            self._logger.info(
                "Run finished: %d item(s) in %.1fs (%.1f items/min)",
                scraped, elapsed, (scraped / elapsed * 60) if elapsed else 0,
            )

        if self._metrics is not None:
            self._logger.info("Run metrics", extra={"metrics": self._metrics.snapshot()})