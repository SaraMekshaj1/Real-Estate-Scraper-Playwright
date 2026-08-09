from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

logger = logging.getLogger("scraper")


class FailedUrlEntry(TypedDict):
    url: str
    stage: str          # "listing_page" (hop 2) or "detail_page" (hop 3)
    error: str
    attempts: int
    timestamp: str
    context: dict[str, Any]     # whatever was already known before this fetch (id, name, etc.)
    referer: Optional[str]      # only meaningful for detail_page — the dealer page it came from


RETRYABLE_FRAGMENTS: tuple[str, ...] = (
    "timeout", "timed out",
    "circuit breaker", "circuit open",
    "connection reset", "connectionreset", "connection refused", "connectionrefused", "connection error",
    "503", "429", "too many requests", "service unavailable",
    "browser has been closed", "browser appears dead", "target closed", "page crashed",
    "network", "eof occurred", "broken pipe", "ssl", "read timeout",
    "net::err",  
)

NON_RETRYABLE_FRAGMENTS: tuple[str, ...] = (
    "404", "not found", "validation", "parseerror", "parse error",
    "attributeerror", "keyerror", "valueerror",
)


def is_retryable(error: str) -> bool:
    low = error.lower()
    for fragment in NON_RETRYABLE_FRAGMENTS:
        if fragment in low:
            return False
    for fragment in RETRYABLE_FRAGMENTS:
        if fragment in low:
            return True
    return False

def full_error_text(exc: BaseException) -> str:
    """
    Flattens an exception and its __cause__/__context__ chain into one
    string. Needed because a wrapping exception's own message (e.g.
    "All 3 attempts failed for {url}") is often generic — the actual
    reason (e.g. "net::ERR_NAME_NOT_RESOLVED") usually lives on the
    original exception it was raised `from`, not on the wrapper itself.
    """
    parts = []
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(parts)

class FailedUrlStore:
    """
    Persistent, asyncio-safe store for URLs that failed with a retryable
    error during a crawl. Each entry is tagged with WHICH hop it failed
    at, so a later retry knows whether it needs to re-run the full
    listing -> detail chain (stage="listing_page") or can jump straight to
    re-fetching one known page (stage="detail_page").
    """
    

    def __init__(self, path: str = "output/failed_urls.json") -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._data: dict[str, FailedUrlEntry] = {}
        self._load_sync()

    def _load_sync(self) -> None:
        if not self._path.exists():
            return
        try:
            raw: list[FailedUrlEntry] = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = {entry["url"]: entry for entry in raw}
            logger.info("FailedUrlStore: loaded %d entries from %s", len(self._data), self._path)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("FailedUrlStore: corrupt file at %s (%s) — starting fresh", self._path, exc)
            self._data = {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(list(self._data.values()), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def record(
        self,
        url: str,
        error: str,
        stage: str,
        context: Optional[dict[str, Any]] = None,
        referer: Optional[str] = None,
    ) -> None:
        async with self._lock:
            existing = self._data.get(url)
            if existing:
                existing["attempts"] += 1
                existing["error"] = error
                existing["timestamp"] = _now()
                # stage/context/referer intentionally left as first-recorded —
                # they describe where this URL sits in the pipeline, which
                # doesn't change between attempts.
            else:
                self._data[url] = FailedUrlEntry(
                    url=url,
                    stage=stage,
                    error=error,
                    attempts=1,
                    timestamp=_now(),
                    context=context or {},
                    referer=referer,
                )
            self._flush()
            logger.debug("FailedUrlStore: recorded failure for %s (stage=%s, %s)", url, stage, error)

    async def remove(self, url: str) -> None:
        async with self._lock:
            if url in self._data:
                del self._data[url]
                self._flush()

    def pending(self, max_attempts: int, stage: Optional[str] = None) -> list[FailedUrlEntry]:
        entries = [e for e in self._data.values() if e["attempts"] <= max_attempts]
        if stage is not None:
            entries = [e for e in entries if e["stage"] == stage]
        return entries

    def __len__(self) -> int:
        return len(self._data)
    
def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()