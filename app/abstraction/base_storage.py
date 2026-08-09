from __future__ import annotations

import abc
from typing import Any, Iterator


class BaseStorage(abc.ABC):
    """
    Contract for an in-run record store — useful for dedup checks
    (`exists()`) or building a final summary (`all()`, `count()`)
    without depending on a specific backend. InMemoryStorage is the
    default; swap for Redis/SQLite/Postgres without touching callers.
    """

    @abc.abstractmethod
    def save(self, record: dict[str, Any]) -> None: ...

    @abc.abstractmethod
    def exists(self, record_id: Any) -> bool: ...

    @abc.abstractmethod
    def all(self) -> Iterator[dict[str, Any]]: ...

    @abc.abstractmethod
    def count(self) -> int: ...
