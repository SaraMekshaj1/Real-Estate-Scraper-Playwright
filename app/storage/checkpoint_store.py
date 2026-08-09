from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any
from app.abstraction.base_checkpoint_store import BaseCheckpointStore

logger = logging.getLogger(__name__)


class JsonCheckpointStore(BaseCheckpointStore):
    """
    Key-value store backed by a JSON file. Fine for a single-process
    scraper up to ~50k keys. Rewritten in full on every save() — simple
    and crash-safe (no partial-write torn state) at the cost of O(n)
    writes; switch to a SQLite-backed store if that becomes the
    bottleneck on a very large site.
    """

    def __init__(self, path: str = "output/checkpoint.json") -> None:
        self._path = Path(path)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Checkpoint loaded from %s (%d keys)", self._path, len(self._data))
            except json.JSONDecodeError:
                logger.warning("Corrupt checkpoint at %s — starting fresh", self._path)
                self._data = {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._flush()

    def load(self, key: str) -> Any | None:
        return self._data.get(key)

    def exists(self, key: str) -> bool:
        return key in self._data

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._flush()

    def keys(self, prefix: str = "") -> list[str]:
        if not prefix:
            return list(self._data.keys())
        return [k for k in self._data if k.startswith(prefix)]