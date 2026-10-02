"""
FInsight Trading Engine — Base Ingestor
========================================
Abstract base class providing shared infrastructure for all data ingestors:
  - Exponential backoff retry with configurable attempts and jitter
  - Token-bucket rate limiter (respects Kite's 3 req/sec hard limit)
  - Structured logging with per-class logger names
  - Strategy config loading (strategy_config.yaml)
  - NSE HTTP session with browser-like headers to avoid 403 errors

All concrete ingestors MUST inherit from BaseIngestor and call super().__init__().
"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import yaml

# ---------------------------------------------------------------------------
# Module-level logger — each subclass will use its own child logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# Path to the project root strategy_config.yaml (two levels above data/ingestion/)
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "strategy_config.yaml"


def _load_strategy_config() -> dict:
    """
    Load and return the strategy_config.yaml as a plain dict.

    Raises:
        FileNotFoundError: if strategy_config.yaml cannot be located.
        yaml.YAMLError: if the file is malformed.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"strategy_config.yaml not found at expected path: {_CONFIG_PATH}"
        )
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Token-bucket rate limiter (thread-safe)
# ---------------------------------------------------------------------------
class _TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Ensures callers do not exceed `rate` calls per second.
    Used to honour Zerodha Kite's 3 requests/second API limit.

    Args:
        rate: Maximum allowed calls per second (e.g. 3 for Kite).
        capacity: Maximum burst capacity (defaults to `rate`).
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self._rate = rate
        self._capacity = capacity if capacity is not None else rate
        self._tokens = self._capacity
        self._last_refill: float = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> None:
        """
        Block until a token is available, then consume one.

        This call is synchronous; callers in tight loops will naturally
        be throttled to `rate` calls per second.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                # Refill tokens proportional to elapsed time
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._rate,
                )
                self._last_refill = now

                if self._tokens >= 1:
                    self._tokens -= 1
                    return  # Token acquired

            # No token available — sleep a short interval before retrying
            time.sleep(1.0 / self._rate / 2)


# ---------------------------------------------------------------------------
# Base Ingestor
# ---------------------------------------------------------------------------
class BaseIngestor(ABC):
    """
    Abstract base class for all FInsight data ingestors.

    Provides:
        * Strategy config loaded from strategy_config.yaml
        * Shared logger scoped to the concrete subclass name
        * Token-bucket rate limiter (default: 3 req/sec for Kite)
        * Retry-with-exponential-backoff decorator / helper
        * Requests session with NSE-compatible browser headers

    Subclasses MUST implement ``ingest()`` (or define their own public API
    methods that call ``_rate_limited_call()`` for any external API hit).

    Args:
        kite_rate_per_sec: Kite API rate limit.  Default is 3 req/sec.
        max_retries: Maximum retry attempts on transient errors.
        base_backoff_sec: Initial back-off interval in seconds.
        max_backoff_sec: Upper cap on back-off interval (seconds).
    """

    #: Kite Connect enforces 3 requests/second across all endpoints.
    KITE_RATE_PER_SEC: float = 3.0

    def __init__(
        self,
        kite_rate_per_sec: float = KITE_RATE_PER_SEC,
        max_retries: int = 5,
        base_backoff_sec: float = 1.0,
        max_backoff_sec: float = 60.0,
    ) -> None:
        # Scoped logger — shows the concrete class name in log output
        self.logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

        # Load strategy config once at construction
        self.config: dict = _load_strategy_config()

        # Retry parameters
        self._max_retries = max_retries
        self._base_backoff_sec = base_backoff_sec
        self._max_backoff_sec = max_backoff_sec

        # Shared token-bucket rate limiter for Kite API calls
        self._rate_limiter = _TokenBucket(rate=kite_rate_per_sec)

        # Lazy-initialised requests.Session for NSE HTTP calls
        self._nse_session: Any = None  # set by _get_nse_session()

        self.logger.debug(
            "Initialised %s (rate=%.1f req/s, max_retries=%d)",
            self.__class__.__name__,
            kite_rate_per_sec,
            max_retries,
        )

    # ------------------------------------------------------------------
    # Public helpers — used by subclasses
    # ------------------------------------------------------------------

    def _rate_limited_call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute *fn* after acquiring a rate-limit token.

        Wraps the call in the token-bucket rate limiter so that no more
        than ``kite_rate_per_sec`` calls are made per second.

        Args:
            fn: Callable to invoke (typically a kiteconnect method).
            *args: Positional arguments forwarded to *fn*.
            **kwargs: Keyword arguments forwarded to *fn*.

        Returns:
            Whatever *fn* returns.
        """
        self._rate_limiter.acquire()
        return fn(*args, **kwargs)

    def _with_retry(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute *fn* with exponential-backoff retries on transient errors.

        Retries on the following exception types:
            - ``ConnectionError`` / ``TimeoutError`` (network issues)
            - ``Exception`` subclasses whose message contains the strings
              ``'429'``, ``'503'``, ``'rate limit'``, or ``'timeout'``
              (API throttle / overload signals)

        The back-off interval grows as ``base × 2^attempt`` plus random
        jitter (±20 %) to avoid thundering-herd on a shared API.

        Args:
            fn: Callable to attempt.
            *args: Positional arguments forwarded to *fn*.
            **kwargs: Keyword arguments forwarded to *fn*.

        Returns:
            Whatever *fn* returns on success.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc).lower()
                is_transient = any(
                    token in exc_str
                    for token in ("429", "503", "rate limit", "timeout", "connection")
                ) or isinstance(exc, (ConnectionError, TimeoutError))

                if attempt == self._max_retries or not is_transient:
                    self.logger.error(
                        "Non-retryable error (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                        exc_info=True,
                    )
                    raise

                # Exponential back-off with ±20 % jitter
                backoff = min(
                    self._base_backoff_sec * (2 ** attempt),
                    self._max_backoff_sec,
                )
                jitter = backoff * random.uniform(-0.2, 0.2)
                sleep_for = max(0.0, backoff + jitter)

                self.logger.warning(
                    "Transient error (attempt %d/%d). Retrying in %.2fs. Error: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    sleep_for,
                    exc,
                )
                time.sleep(sleep_for)
                last_exc = exc

        # Should never be reached, but satisfies the type checker
        raise RuntimeError("Retry loop exhausted") from last_exc

    def _rate_limited_retry(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Convenience wrapper: rate-limit → retry → call.

        Equivalent to ``_with_retry(lambda: _rate_limited_call(fn, ...))``.
        This is the recommended entrypoint for any Kite API call inside a
        subclass.

        Args:
            fn: Callable to invoke (typically a kiteconnect method).
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Whatever *fn* returns.
        """
        return self._with_retry(self._rate_limited_call, fn, *args, **kwargs)

    def _get_nse_session(self):
        """
        Return a ``requests.Session`` configured with realistic browser
        headers that prevent NSE from returning 403 Forbidden.

        The session is lazily initialised and reused across calls to
        amortise TCP handshake costs.

        Returns:
            requests.Session with NSE-compatible headers.
        """
        if self._nse_session is None:
            import requests  # local import to keep module lightweight

            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Referer": "https://www.nseindia.com/",
                    "Connection": "keep-alive",
                    "DNT": "1",
                }
            )
            # Warm up the session cookie by hitting the NSE home page once.
            # NSE requires a valid session cookie on most API endpoints.
            try:
                warmup_resp = session.get(
                    "https://www.nseindia.com",
                    timeout=15,
                )
                warmup_resp.raise_for_status()
                self.logger.debug(
                    "NSE session warmed up (status=%d)", warmup_resp.status_code
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "NSE session warmup failed (non-fatal): %s", exc
                )

            self._nse_session = session
        return self._nse_session

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def ingest(self, *args: Any, **kwargs: Any) -> Any:
        """
        Main ingestion entry point.  Each concrete ingestor implements
        this with its own signature and documentation.
        """
