from __future__ import annotations
import re
from typing import Any, Optional
from app.abstraction.base_normalizer import BaseNormalizer
from app.exceptions.scraper_exceptions import NormalizationError


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F9FF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\uFE00-\uFEFF"
    "]+",
    flags=re.UNICODE,
)

# lowercase only — comparison is done via .lower()
_INVALID_STATUS_VALUES = {
    "listimet e fundit",
    "te rekomanduara",
    "featured",
    "recent listings",
}

class TextNormalizer(BaseNormalizer):
    """Default normalizer: trims whitespace, collapses internal whitespace,
    treats empty string as None. Safe fallback for any field without a
    more specific normalizer registered."""

    def normalize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None


class CleanTextNormalizer(BaseNormalizer):
    """Like TextNormalizer, but also strips emoji and wrapping quote
    characters. Use for free-text fields scraped from real-estate
    listings (title, description, location, ...)."""

    def normalize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = _EMOJI_PATTERN.sub("", str(value))
        text = " ".join(text.split())
        text = text.strip("'\"\u201c\u201d\u2018\u2019")
        return text or None


class NumberNormalizer(BaseNormalizer):
    """Extracts the first numeric token from a string, e.g. '150 m2' ->
    '150'. Kept as a string (not float) — these are display fields
    (area, floor, bedroom count), not arithmetic values."""

    _PATTERN = re.compile(r"\d+(?:[.,]\d+)?")

    def normalize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        match = self._PATTERN.search(str(value))
        if not match:
            return None
        return match.group().replace(",", ".")


class StatusNormalizer(BaseNormalizer):
    """Cleans a status string and discards known placeholder/nav-label
    values that show up in the same DOM slot as real statuses."""

    _cleaner = CleanTextNormalizer()

    def normalize(self, value: Any) -> Optional[str]:
        cleaned = self._cleaner.normalize(value)
        if not cleaned:
            return None
        return None if cleaned.lower() in _INVALID_STATUS_VALUES else cleaned


class YesNoNormalizer(BaseNormalizer):
    """Normalizes Albanian/English yes-no raw strings (optionally
    prefixed with a 'Label: ' segment) to 'Yes' / 'No'."""

    def normalize(self, value: Any) -> Optional[str]:
        if not value:
            return None
        v = str(value).strip()
        if ":" in v:
            v = v.split(":", 1)[1].strip()
        lower = v.lower()
        if lower in ("po", "yes"):
            return "Yes"
        if lower in ("jo", "no"):
            return "No"
        return v

class PriceNormalizer(BaseNormalizer):
    """Handles mixed thousands/decimal separator conventions
    ('1.250,50' vs '1,250.50' vs '92,000' vs '92.5'). Returns None
    (not a raised error) on anything unparsable, since a bad price on
    one listing shouldn't abort the whole run — see ScrapingService,
    which doesn't catch NormalizationError around normalization."""

    def normalize(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        cleaned = re.sub(r"[^\d.,]", "", str(value))
        if not cleaned:
            return None

        if "," in cleaned and "." in cleaned:
            if cleaned.index(".") < cleaned.index(","):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            after_comma = cleaned.split(",")[-1]
            cleaned = cleaned.replace(",", "") if len(after_comma) == 3 else cleaned.replace(",", ".")
        elif "." in cleaned:
            after_dot = cleaned.split(".")[-1]
            if len(after_dot) == 3:
                cleaned = cleaned.replace(".", "")

        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
