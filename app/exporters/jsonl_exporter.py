from __future__ import annotations
import json
import logging
from typing import Any, Optional, TextIO
from app.abstraction.base_exporter import BaseExporter
from app.config.settings import Settings
from app.exceptions.scraper_exceptions import ExportError


class JSONLExporter(BaseExporter):
    """
    Streams one JSON object per line (JSON Lines / .jsonl), flushed
    after every row. Unlike a single JSON array file (which only
    becomes valid once close() writes the closing bracket), this
    format is genuinely safe to write incrementally — if the process
    dies mid-run, every row written so far is already durable and
    independently parseable.
    """

    def __init__(self, settings: Settings, filename: Optional[str] = None, logger: Optional[logging.Logger] = None) -> None:
        self._settings = settings
        self._filename = filename or settings.jsonl_filename
        self._logger = logger or logging.getLogger(__name__)
        self._file: Optional[TextIO] = None
        self._count = 0

    def open(self) -> None:
        output_dir = self._settings.ensure_output_dir()
        dest = output_dir / self._filename
        mode = "a" if dest.exists() and dest.stat().st_size > 0 else "w"
        try:
            self._file = dest.open(mode, encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Failed to open {dest} for writing: {exc}") from exc

    def write_row(self, row: dict[str, Any]) -> None:
        if self._file is None:
            raise ExportError("JSONLExporter.write_row called before open()")
        try:
            self._file.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._file.flush()
        except (TypeError, ValueError, OSError) as exc:
            raise ExportError(f"Failed to write row {row!r}: {exc}") from exc
        self._count += 1

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._logger.info("JSONL export complete: %d record(s) -> %s", self._count, self._filename)
        self._file = None
