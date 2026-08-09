from __future__ import annotations


class ScraperError(Exception):
    """Base exception for every error raised anywhere in this project."""


class ConfigError(ScraperError):
    """Raised when configuration is missing or invalid."""


class ClientError(ScraperError):
    """Raised when an HTTP/browser-level request fails."""


class PageNotFoundError(ClientError):
    """
    Raised when a page returns 404 — the resource doesn't exist.
    NOT a bot-detection or health signal: never counts toward a
    circuit breaker, never retried, always a quiet skip.
    """


class CaptchaDetectedError(ClientError):
    """
    Raised when a response is a bot-check/CAPTCHA page instead of real
    content. A HARD signal — triggers a cooldown, not a fast retry
    (retrying immediately after a bot-check usually just re-triggers it).
    """


class SoftBlockError(ClientError):
    """
    Raised when a page loads normally (200, no CAPTCHA) but expected
    content is missing — a soft anti-scraping degrade rather than a
    hard block. Signals the client to rotate its session, not just
    back off. Detected via a site-specific `content_validator`, since
    there's no generic way to know what "expected content" looks like.
    """


class ParsingError(ScraperError):
    """Raised when raw content cannot be parsed into structured data."""


class MappingError(ScraperError):
    """Raised when a parsed dict cannot be mapped to a domain model."""


class NormalizationError(ScraperError):
    """Raised when a value cannot be normalized/cleaned."""


class ValidationError(ScraperError):
    """Raised when a record fails a validation rule."""


class CrawlError(ScraperError):
    """Raised when the crawler cannot continue (broken pagination, dead link…)."""


class ExportError(ScraperError):
    """Raised when data cannot be persisted to an output medium."""


class StorageError(ScraperError):
    """Raised when the in-run storage backend fails to save/read data."""
