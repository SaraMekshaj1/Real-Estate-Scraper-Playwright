from __future__ import annotations

import abc
from typing import Any


class BaseValidator(abc.ABC):
    """
    Contract for rejecting a mapped Item that doesn't meet minimum
    quality standards (e.g. required fields present). This is also
    where SOFT-BLOCKED records get caught in practice: a page that
    loaded fine but came back with everything empty should fail
    validation rather than silently landing in your export as a
    mostly-blank row.
    """

    @abc.abstractmethod
    def validate(self, item: Any) -> None:
        """Raise ValidationError if *item* doesn't meet requirements."""
