from __future__ import annotations
import logging
from typing import Any, Iterable, Optional, Sequence
from app.abstraction.base_exporter import BaseExporter


class ExportService:
    """
    Fan-out items to every configured exporter (CSV + JSONL + …) —
    incrementally, not in one final batch.

    Lifecycle: start() once at the beginning of a run (opens every
    exporter's sink), export_batch() once per page as results come in
    (writes immediately, exporters stay open across calls), finish()
    once at the end (closes everything). This is what makes a scrape
    crash-safe: kill the process at any point and everything written up
    to that point is already durable on disk.

    Do NOT open()/close() an exporter per batch — for a file-based
    exporter opened in "w" mode, that would truncate the file on every
    call and destroy everything written before it.
    """

    def __init__(self, exporters: Sequence[BaseExporter], logger: Optional[logging.Logger] = None) -> None:
        self._exporters = exporters
        self._logger = logger or logging.getLogger(__name__)
        self._started = False
        self._total_exported = 0

    def start(self) -> None:
        for exporter in self._exporters:
            exporter.open()
        self._started = True
        self._total_exported = 0
        self._logger.info("Export started — writing incrementally as pages are scraped.")

    def export_batch(self, items: Iterable[Any]) -> None:
        if not self._started:
            raise RuntimeError("ExportService.export_batch() called before start()")

        rows = [item.to_dict() for item in items]
        if not rows:
            return

        for exporter in self._exporters:
            exporter.write_batch(rows)
        self._total_exported += len(rows)
        self._logger.debug("Exported %d row(s), %d total so far", len(rows), self._total_exported)

    def finish(self) -> None:
        for exporter in self._exporters:
            exporter.close()
        self._started = False
        self._logger.info("Export finished: %d record(s) total.", self._total_exported)
