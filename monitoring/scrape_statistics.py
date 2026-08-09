from __future__ import annotations


class ScrapeStatistics:
    """Simple run-level counters. Extend as needed (per-status counts,
    timing histograms, etc.) — kept minimal here on purpose."""

    def __init__(self, expected: int = 0) -> None:
        self.expected = expected
        self.succeeded = 0
        self.failed = 0

    def record_success(self) -> None:
        self.succeeded += 1

    def record_failure(self) -> None:
        self.failed += 1
