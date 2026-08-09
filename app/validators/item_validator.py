from __future__ import annotations
from typing import Any, Sequence
from app.abstraction.base_validator import BaseValidator
from app.exceptions.scraper_exceptions import ValidationError


class ItemValidator(BaseValidator):
    """
    Fails an item if any field in `required_fields` is missing/empty.

    ADAPT PER PROJECT: set required_fields to whatever fields make a
    record actually USEFUL for this project (e.g. ("phone", "address")).
    Leaving this empty means a record with everything blank still
    passes validation and gets exported — which is exactly how a soft
    block (page loads fine, contact data quietly missing) can slip
    through as an empty row unnoticed. Setting real required_fields is
    what turns that into a visible "Skipping record" warning instead.
    """

    def __init__(self, required_fields: Sequence[str] = ()) -> None:
        self._required_fields = required_fields

    def validate(self, item: Any) -> None:
        for field_name in self._required_fields:
            value = getattr(item, field_name, None)
            if value in (None, "", []):
                raise ValidationError(f"Missing required field '{field_name}' on {item!r}")
