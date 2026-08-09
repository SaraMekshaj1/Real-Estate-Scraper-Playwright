from __future__ import annotations
import csv
import logging
from typing import Any, Optional, TextIO
from app.abstraction.base_exporter import BaseExporter
from app.config.settings import Settings
from app.exceptions.scraper_exceptions import ExportError


class CSVExporter(BaseExporter):
    """
    Streams rows to a CSV file as they arrive. Header is inferred from
    the first row written; extra keys on later rows are ignored rather
    than crashing the whole export. Flushed after every row so an
    interrupted run still has everything written so far on disk.
    """

    def __init__(self, settings: Settings, filename: Optional[str] = None, logger: Optional[logging.Logger] = None) -> None:
        self._settings = settings
        self._filename = filename or settings.csv_filename
        self._logger = logger or logging.getLogger(__name__)
        self._file: Optional[TextIO] = None
        self._writer: Optional[csv.DictWriter] = None

    def open(self) -> None:
        output_dir = self._settings.ensure_output_dir()
        dest = output_dir / self._filename
        resume = dest.exists() and dest.stat().st_size > 0

        existing_fieldnames: Optional[list[str]] = None
        if resume:
            with dest.open("r", newline="", encoding="utf-8") as f:
                existing_fieldnames = next(csv.reader(f), None)

        try:
            self._file = dest.open("a" if resume else "w", newline="", encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Failed to open {dest} for writing: {exc}") from exc

        if existing_fieldnames:
            self._writer = csv.DictWriter(self._file, fieldnames=existing_fieldnames, extrasaction="ignore")
            self._logger.info("Resuming %s — appending under existing %d-column header", self._filename, len(existing_fieldnames))

    def write_row(self, row: dict[str, Any]) -> None:
        if self._file is None:
            raise ExportError("CSVExporter.write_row called before open()")

        if self._writer is None:
            self._writer = csv.DictWriter(self._file, fieldnames=list(row.keys()), extrasaction="ignore")
            self._writer.writeheader()

        try:
            self._writer.writerow(row)
            self._file.flush()
        except (csv.Error, ValueError) as exc:
            raise ExportError(f"Failed to write row {row!r}: {exc}") from exc

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._logger.info("CSV export complete: %s", self._filename)
        self._file = None
        self._writer = None
