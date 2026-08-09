from __future__ import annotations
from typing import Any, Dict, Iterator
from app.abstraction.base_storage import BaseStorage


class InMemoryStorage(BaseStorage):
    """
    Simple dict-backed storage keyed by a record id. Good default for
    small/medium scrapes or for tests. Swap for a Redis/SQLite/Postgres-
    backed implementation without touching any calling code.
    """

    def __init__(self, id_field: str = "id") -> None:
        self._id_field = id_field
        self._records: Dict[Any, dict[str, Any]] = {}

    def save(self, record: dict[str, Any]) -> None:
        record_id = record.get(self._id_field)
        self._records[record_id] = record

    def exists(self, record_id: Any) -> bool:
        return record_id in self._records

    def all(self) -> Iterator[dict[str, Any]]:
        return iter(self._records.values())

    def count(self) -> int:
        return len(self._records)
