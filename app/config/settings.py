from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val is not None else default


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    return float(val) if val is not None else default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """
    Central, immutable configuration object.

    ADAPT PER PROJECT: base_url, and possibly the delay/concurrency
    values if the target site tolerates more/less. Everything else is
    generic to any project built on this skeleton.

    Values are read from environment variables (via a .env file loaded
    by python-dotenv, or exported manually). Nothing here is hardcoded
    to a real target — see .env.example.
    """

    # --- Target --------------------------------------------------------
    base_url: str = field(default_factory=lambda: _env("BASE_URL", ""))

    # --- Client mode -----------------------------------------------------
    # "http"    -> AsyncHttpClient (aiohttp). Fast, cheap. Use this by
    #              default — try it FIRST on every new project.
    # "browser" -> BrowserClient (Playwright). Slower, heavier, but
    #              renders like a real browser. Switch to this only if
    #              the site needs JS rendering or actively blocks plain
    #              HTTP clients.
    client_mode: str = field(default_factory=lambda: _env("CLIENT_MODE", "browser"))

    # --- HTTP client (aiohttp) --------------------------------------------
    user_agent: str = field(
        default_factory=lambda: _env(
            "USER_AGENT", "Mozilla/5.0 (compatible; GenericScraper/1.0)"
        )
    )
    request_timeout: float = field(default_factory=lambda: _env_float("REQUEST_TIMEOUT", 20.0))
    verify_ssl: bool = field(default_factory=lambda: _env_bool("VERIFY_SSL", True))

    # --- Browser client (Playwright) --------------------------------------
    browser_headless: bool = field(default_factory=lambda: _env_bool("BROWSER_HEADLESS", True))
    rotate_user_agents: bool = field(default_factory=lambda: _env_bool("ROTATE_USER_AGENTS", True))
    session_rotate_after: int = field(default_factory=lambda: _env_int("SESSION_ROTATE_AFTER", 80))

    # --- Shared pacing / resilience ----------------------------------------
    request_delay_min_secs: float = field(default_factory=lambda: _env_float("REQUEST_DELAY_MIN_SECS", 3.0))
    request_delay_max_secs: float = field(default_factory=lambda: _env_float("REQUEST_DELAY_MAX_SECS", 5.0))
    retry_max_attempts: int = field(default_factory=lambda: _env_int("RETRY_MAX_ATTEMPTS", 3))
    captcha_cooldown_seconds: float = field(default_factory=lambda: _env_float("CAPTCHA_COOLDOWN_SECONDS", 60.0))

    # Requests-per-minute cap enforced globally (HTTP client only).
    # 0 = disabled (concurrency cap is the only throttle).
    rate_limit_rpm: int = field(default_factory=lambda: _env_int("RATE_LIMIT_RPM", 0))

    # --- Concurrency -----------------------------------------------------
    # HTTP mode can usually go much higher (10-30). Browser mode should
    # stay small (3-5) — each concurrent request is a real browser page.
    max_concurrent_requests: int = field(default_factory=lambda: _env_int("MAX_CONCURRENT_REQUESTS", 5))

    # --- Crawling --------------------------------------------------------
    max_pages: int = field(default_factory=lambda: _env_int("MAX_PAGES", 0))  # 0 = unlimited

    # --- Pagination --------------------------------------------------------
    next_page_selector: str = field(default_factory=lambda: _env("NEXT_PAGE_SELECTOR", ""))

    # --- Output ----------------------------------------------------------
    output_dir: str = field(default_factory=lambda: _env("OUTPUT_DIR", "output"))
    csv_filename: str = field(default_factory=lambda: _env("CSV_FILENAME", "results.csv"))
    jsonl_filename: str = field(default_factory=lambda: _env("JSONL_FILENAME", "results.jsonl"))

    # --- Logging -----------------------------------------------------------
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    # "json" for structured/production logs, "text" for local dev.
    log_format: str = field(default_factory=lambda: _env("LOG_FORMAT", "text"))
    # Path to a log file, e.g. "scraper.log". Empty string = console only.
    log_file: str = field(default_factory=lambda: _env("LOG_FILE", ""))

    checkpoint_path: str = "output/checkpoint.json"
    failed_urls_path: str = "output/failed_urls.json"
    enable_resume: bool = True
    
    def ensure_output_dir(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path
