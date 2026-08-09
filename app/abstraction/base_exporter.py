from __future__ import annotations

import abc
from typing import Any


class BaseExporter(abc.ABC):
    """
    Contract for all data exporters (CSV, JSONL, DB, S3 …).

    Design notes:
      - write_row() is the ONLY mandatory method (ISP: a minimal
        exporter needs nothing else).
      - open()/close() default to no-ops so simple exporters aren't
        forced to implement lifecycle hooks they don't need.
      - write_batch() has a correct default (loop over write_row) and
        is opt-in to override (OCP: a DB exporter could override it to
        run one multi-row INSERT + one commit instead of N).
      - Overrides of write_batch() must keep the same idempotency
        guarantee as write_row() (safe to call again with an
        already-seen record).
    """

    def open(self) -> None:
        """Prepare the output sink (open file, acquire DB connection …). Default: no-op."""

    @abc.abstractmethod
    def write_row(self, row: dict[str, Any]) -> None:
        """Persist a single row. Must be idempotent on duplicate keys."""

    def write_batch(self, rows: list[dict[str, Any]]) -> None:
        """DEFAULT: iterates write_row(). Override to gain a single commit/flush instead of N."""
        for row in rows:
            self.write_row(row)

    def close(self) -> None:
        """Flush buffers and release resources. Default: no-op."""

    def __enter__(self) -> "BaseExporter":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
