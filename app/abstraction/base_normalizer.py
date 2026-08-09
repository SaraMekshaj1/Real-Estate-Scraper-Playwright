from __future__ import annotations

import abc
from typing import Any


class BaseNormalizer(abc.ABC):
    """
    Contract for cleaning/coercing a single field's raw value (e.g.
    "$12,500.00" -> 12500.0, "4.5 stars" -> 4.5). ScrapingService looks
    one up per field by name, falling back to a default normalizer for
    any field without a specific one registered.
    """

    @abc.abstractmethod
    def normalize(self, value: Any) -> Any:
        """Return the cleaned value. Raise NormalizationError on failure."""
