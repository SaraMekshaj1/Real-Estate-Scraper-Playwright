from __future__ import annotations
import abc
from typing import Any


class BaseCheckpointStore(abc.ABC):
    """
    Generic key-value contract for run/dedup bookkeeping — deliberately
    separate from BaseStorage, which persists whole scraped records.
    This store persists small facts: "has URL X already been exported",
    "did the last run finish cleanly". Swap backends (JSON, SQLite,
    Redis) without touching DeduplicationService or FailedUrlStore.
    """

    @abc.abstractmethod
    def save(self, key: str, value: Any) -> None: ...

    @abc.abstractmethod
    def load(self, key: str) -> Any | None: ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    def keys(self, prefix: str = "") -> list[str]: ...