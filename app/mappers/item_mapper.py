from __future__ import annotations
from typing import Any
from app.abstraction.base_mapper import BaseMapper
from app.exceptions.scraper_exceptions import MappingError
from app.models.item import Property


class PropertyMapper(BaseMapper[Property]):
    """
    Converts a normalized raw dict (parser output, post-normalization,
    no context merge in this project) into a Property instance. Renames
    site-specific raw keys (statusi, lloji, mobilimi, ka_hipoteke,
    ashensor, karakteristikat, price_raw) to the model's English field
    names — this is the only place that renaming happens.
    """

    def map(self, raw: dict[str, Any]) -> Property:
        try:
            return Property(
                property_id=raw.get("property_id"),
                url=raw["url"],
                title=raw.get("title"),
                price=self._to_float(raw.get("price_raw")),
                price_currency=raw.get("price_currency"),
                location=raw.get("location"),
                description=raw.get("description"),
                images=raw.get("images"),
                total_area=raw.get("total_area"),
                internal_area=raw.get("internal_area"),
                number_of_bedrooms=raw.get("number_of_bedrooms"),
                floor=raw.get("floor"),
                status=raw.get("statusi"),
                type=raw.get("lloji"),
                furnished=raw.get("mobilimi"),
                mortgage=raw.get("ka_hipoteke"),
                elevator=raw.get("ashensor"),
                number_of_toilets=raw.get("number_of_toilets"),
                characteristics=raw.get("karakteristikat"),
            )
        except KeyError as exc:
            raise MappingError(f"Failed to map record {raw!r}: missing required key {exc}") from exc
        except TypeError as exc:
            raise MappingError(f"Failed to map record {raw!r}: {exc}") from exc

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("€", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None