from __future__ import annotations

import abc
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class BaseMapper(abc.ABC, Generic[T]):
    """
    Contract for converting a raw, normalized, context-merged dict into
    a typed domain model (your project's `Item`). Keeping this as its
    own step (separate from parsing) means validation/export always
    deal with a typed object, never a loosely-shaped dict.
    """

    @abc.abstractmethod
    def map(self, raw: dict[str, Any]) -> T:
        """Convert *raw* into a domain model instance. Raise MappingError on failure."""
