"""
FInsight Trading Engine — OHLCV Ingestor
==========================================
Fetches raw, unadjusted end-of-day OHLCV data from the Zerodha Kite Connect
API and persists it to the ``market_data_lake`` table.

CRITICAL DATA INTEGRITY RULES (DO NOT VIOLATE):
    1. ``continuous=False`` is ALWAYS passed to ``kite.historical_data()`` to
       receive un-adjusted prices.  Kite returns adjusted prices when
       ``continuous=True``.  We NEVER want adjusted prices at storage time.
    2. Only raw open/high/low/close/volume are stored.  Adjustment factors are
       applied in-memory in ``engine_core/adjustments.py``.
    3. ADTV = SMA(raw_close × raw_volume, 20) — volume and close used here
       are ALWAYS the raw columns from market_data_lake.
    4. Market Cap = raw_close × raw_shares_outstanding — raw_close only.

Usage:
    from data.ingestion.ohlcv_ingestor import OHLCVIngestor
    from datetime import date

    ingestor = OHLCVIngestor(kite_instance)
    rows_inserted = ingestor.ingest_symbol("RELIANCE", date(2024, 1, 1), date(2024, 12, 31))
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from data.db.connection import get_session
from data.db.models import MarketDataLake
from data.ingestion.base_ingestor import BaseIngestor

load_dotenv()

logger = logging.getLogger(__name__)

# NSE trading calendar: weekday Mon-Fri excluding public holidays.
# We approximate using pandas business-day calendar; the holiday list below
# covers NSE market holidays for the near term and should be kept updated.
# In production, replace with an authoritative NSE holiday API response.
_NSE_HOLIDAYS: list[date] = [
    # 2024 NSE holidays (illustrative — update annually)
    date(2024, 1, 22),  # Prana Pratishtha Ceremony
    date(2024, 2, 19),  # Chhatrapati Shivaji Maharaj Jayanti
    date(2024, 3, 25),  # Holi
    date(2024, 3, 29),  # Good Friday
    date(2024, 4, 11),  # Id-Ul-Fitr (Ramadan Eid)
    date(2024, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2024, 4, 17),  # Ram Navami
    date(2024, 4, 21),  # Mahavir Jayanti
    date(2024, 5, 23),  # Buddha Pournima
    date(2024, 6, 17),  # Eid Ul Adha (Bakri Eid)
    date(2024, 7, 17),  # Muharram
    date(2024, 8, 15),  # Independence Day
    date(2024, 10, 2),  # Mahatma Gandhi Jayanti
    date(2024, 11, 1),  # Diwali Laxmi Puja
    date(2024, 11, 15), # Gurunanak Jayanti
    date(2024, 12, 25), # Christmas
    # 2025 NSE holidays (illustrative — update annually)
    date(2025, 2, 26),  # Mahashivratri
    date(2025, 3, 14),  # Holi
    date(2025, 3, 31),  # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),  # Shree Ram Navami
    date(2025, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 12),  # Buddha Pournima
    date(2025, 6, 7),   # Eid Ul Adha (Bakri Eid)
    date(2025, 7, 6),   # Muharram
    date(2025, 8, 15),  # Independence Day
    date(2025, 8, 27),  # Ganesh Chaturthi
    date(2025, 10, 2),  # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 20), # Diwali Laxmi Puja
    date(2025, 10, 21), # Diwali Balipratipada
    date(2025, 11, 5),  # Prakash Gurpurb Sri Guru Nanak Dev Ji
    date(2025, 12, 25), # Christmas
]

_NSE_HOLIDAY_SET: frozenset[date] = frozenset(_NSE_HOLIDAYS)

# Kite historical data interval for EOD bars
_KITE_INTERVAL = "day"

# Maximum number of calendar days Kite allows in a single historical_data call.
# Kite's day-interval endpoint supports up to 2000 trading-day chunks.
# We use a conservative 365-day window per API call to stay well within limits.
_MAX_DAYS_PER_KITE_CALL = 365


class OHLCVIngestor(BaseIngestor):
    """
    Fetches raw unadjusted EOD OHLCV from Zerodha Kite and stores it in
    ``market_data_lake``.

    INVARIANT: ``continuous=False`` is ALWAYS used.  Prices stored are the
    exchange-reported raw values; no backward adjustment is applied here.

    Args:
        kite: An authenticated ``kiteconnect.KiteConnect`` instance.
              Pass ``None`` only in unit-test contexts where the DB is mocked.
        exchange: Exchange prefix for instrument lookup (default ``"NSE"``).
    """

    def __init__(self, kite: Any, exchange: str = "NSE") -> None:
        super().__init__()
        self._kite = kite
        self._exchange = exchange
        # Cache instrument_token lookups to avoid repeated API calls
        self._token_cache: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, symbol: str, from_date: date, to_date: date) -> int:
        """
        Convenience alias so BaseIngestor's abstract ``ingest()`` is satisfied.

        Delegates to ``ingest_symbol()``.

        Args:
            symbol: NSE ticker symbol (e.g. ``"RELIANCE"``).
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            Number of OHLCV rows inserted/updated.
        """
        return self.ingest_symbol(symbol, from_date, to_date)

    def ingest_symbol(
        self, symbol: str, from_date: date, to_date: date
    ) -> int:
        """
        Fetch and persist raw unadjusted EOD OHLCV for a single symbol.

        Splits the date range into ``_MAX_DAYS_PER_KITE_CALL``-day chunks
        and issues one Kite API call per chunk to stay within API limits.
        Uses SQLite ``INSERT OR REPLACE`` (upsert) so re-running is idempotent.

        Args:
            symbol: NSE ticker (e.g. ``"INFY"``).
            from_date: Start of date range (inclusive).
            to_date: End of date range (inclusive, must be ≥ from_date).

        Returns:
            Total number of rows upserted (includes no-change rows replaced).

        Raises:
            ValueError: If from_date > to_date.
            RuntimeError: If the instrument token cannot be resolved.
        """
        if from_date > to_date:
            raise ValueError(
                f"from_date ({from_date}) must not be after to_date ({to_date})"
            )

        self.logger.info(
            "Ingesting OHLCV for %s from %s to %s", symbol, from_date, to_date
        )

        instrument_token = self._resolve_instrument_token(symbol)
        total_rows = 0

        # Chunk the date range to avoid Kite's per-call limit
        current_start = from_date
        while current_start <= to_date:
            chunk_end = min(
                current_start + timedelta(days=_MAX_DAYS_PER_KITE_CALL - 1),
                to_date,
            )
            rows = self._fetch_and_store_chunk(
                symbol, instrument_token, current_start, chunk_end
            )
            total_rows += rows
            current_start = chunk_end + timedelta(days=1)

        self.logger.info(
            "Ingested %d OHLCV rows for %s", total_rows, symbol
        )
        return total_rows

    def ingest_universe(
        self, symbols: list[str], from_date: date, to_date: date
    ) -> dict[str, int]:
        """
        Bulk-ingest OHLCV for a list of symbols.

        Processes symbols sequentially; the token-bucket rate limiter inside
        ``_fetch_and_store_chunk`` ensures the 3 req/sec Kite limit is
        respected even across symbols.

        Args:
            symbols: List of NSE tickers.
            from_date: Start of date range (inclusive).
            to_date: End of date range (inclusive).

        Returns:
            Dict mapping each symbol to the number of rows upserted.
        """
        self.logger.info(
            "Bulk-ingesting OHLCV for %d symbols (%s → %s)",
            len(symbols),
            from_date,
            to_date,
        )
        results: dict[str, int] = {}
        for symbol in symbols:
            try:
                results[symbol] = self.ingest_symbol(symbol, from_date, to_date)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Failed to ingest %s: %s", symbol, exc, exc_info=True
                )
                results[symbol] = 0
        return results

    def fill_gaps(self, symbol: str) -> list[date]:
        """
        Detect and fill missing trading-day rows for *symbol*.

        Queries the DB for the earliest and latest date of existing data,
        computes the expected set of NSE trading days in that range, then
        fetches and stores any missing days.

        Args:
            symbol: NSE ticker to check and repair.

        Returns:
            List of dates that were identified as gaps (whether or not fill
            succeeded).  Returns empty list if no gaps found.
        """
        self.logger.info("Checking for OHLCV gaps in %s", symbol)

        with get_session() as session:
            result = session.execute(
                text(
                    "SELECT MIN(trade_date), MAX(trade_date) "
                    "FROM market_data_lake WHERE symbol = :sym"
                ),
                {"sym": symbol},
            ).fetchone()

        if not result or result[0] is None:
            self.logger.warning(
                "No existing data for %s — cannot determine gap range.", symbol
            )
            return []

        min_date: date = (
            result[0] if isinstance(result[0], date) else date.fromisoformat(result[0])
        )
        max_date: date = (
            result[1] if isinstance(result[1], date) else date.fromisoformat(result[1])
        )

        expected_trading_days = self.get_nse_trading_days(min_date, max_date)

        with get_session() as session:
            rows = session.execute(
                text(
                    "SELECT trade_date FROM market_data_lake "
                    "WHERE symbol = :sym AND trade_date BETWEEN :start AND :end"
                ),
                {"sym": symbol, "start": min_date, "end": max_date},
            ).fetchall()

        existing_dates: set[date] = {
            r[0] if isinstance(r[0], date) else date.fromisoformat(r[0])
            for r in rows
        }

        gap_dates = sorted(
            set(expected_trading_days) - existing_dates
        )

        if not gap_dates:
            self.logger.info("No gaps found for %s", symbol)
            return []

        self.logger.warning(
            "Found %d gap dates for %s — back-filling.", len(gap_dates), symbol
        )

        # Back-fill: fetch the full gap window in one ingest_symbol call
        self.ingest_symbol(symbol, min(gap_dates), max(gap_dates))
        return gap_dates

    def get_nse_trading_days(
        self, from_date: date, to_date: date
    ) -> list[date]:
        """
        Return a list of expected NSE trading days in [from_date, to_date].

        A day is a trading day if:
          1. It is a weekday (Mon–Fri).
          2. It is not in the NSE holiday calendar (``_NSE_HOLIDAY_SET``).

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            Sorted list of trading dates.
        """
        trading_days: list[date] = []
        current = from_date
        while current <= to_date:
            if current.weekday() < 5 and current not in _NSE_HOLIDAY_SET:
                trading_days.append(current)
            current += timedelta(days=1)
        return trading_days

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_instrument_token(self, symbol: str) -> int:
        """
        Look up the Kite instrument token for an NSE equity symbol.

        Results are cached in-memory for the lifetime of this ingestor
        instance to avoid redundant API calls across multiple ingestion chunks.

        Args:
            symbol: NSE ticker (e.g. ``"TCS"``).

        Returns:
            Integer Kite instrument token.

        Raises:
            RuntimeError: If the symbol cannot be found in the Kite instruments list.
        """
        cache_key = f"{self._exchange}:{symbol}"
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        self.logger.debug("Resolving instrument token for %s", cache_key)
        instruments: list[dict] = self._rate_limited_retry(
            self._kite.instruments, self._exchange
        )

        for inst in instruments:
            if inst.get("tradingsymbol") == symbol and inst.get("segment") == f"{self._exchange}-EQ":
                token = int(inst["instrument_token"])
                self._token_cache[cache_key] = token
                self.logger.debug("Resolved %s → token %d", cache_key, token)
                return token

        raise RuntimeError(
            f"Instrument token for '{symbol}' on {self._exchange} not found. "
            "Ensure the symbol matches the Kite tradingsymbol exactly."
        )

    def _fetch_and_store_chunk(
        self,
        symbol: str,
        instrument_token: int,
        from_date: date,
        to_date: date,
    ) -> int:
        """
        Fetch one date-range chunk from Kite and upsert into ``market_data_lake``.

        CRITICAL: ``continuous=False`` is the unadjusted price flag. Do NOT
        change this to ``True`` — doing so would store adjusted prices, violating
        the core data integrity contract of this system.

        Args:
            symbol: NSE ticker (used only for the DB row, not the API call).
            instrument_token: Kite integer instrument token.
            from_date: Chunk start date (inclusive).
            to_date: Chunk end date (inclusive).

        Returns:
            Number of rows upserted.
        """
        self.logger.debug(
            "Fetching Kite OHLCV chunk: %s token=%d %s→%s",
            symbol,
            instrument_token,
            from_date,
            to_date,
        )

        # Fetch raw, UNADJUSTED prices — continuous=False is mandatory
        raw_candles: list[dict] = self._rate_limited_retry(
            self._kite.historical_data,
            instrument_token,
            from_date,
            to_date,
            _KITE_INTERVAL,
            continuous=False,  # ← CRITICAL: unadjusted prices
            oi=False,
        )

        if not raw_candles:
            self.logger.debug(
                "No candles returned for %s (%s→%s)", symbol, from_date, to_date
            )
            return 0

        rows = []
        for candle in raw_candles:
            # Kite returns date as a datetime object or ISO string
            candle_date = candle["date"]
            if hasattr(candle_date, "date"):
                candle_date = candle_date.date()
            elif isinstance(candle_date, str):
                candle_date = date.fromisoformat(candle_date[:10])

            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": candle_date,
                    "open_raw": float(candle["open"]),
                    "high_raw": float(candle["high"]),
                    "low_raw": float(candle["low"]),
                    "close_raw": float(candle["close"]),
                    "volume_raw": int(candle["volume"]),
                    "exchange": self._exchange,
                }
            )

        with get_session() as session:
            # INSERT OR REPLACE (SQLite upsert) — idempotent re-runs
            stmt = sqlite_insert(MarketDataLake).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date"],
                set_={
                    "open_raw": stmt.excluded.open_raw,
                    "high_raw": stmt.excluded.high_raw,
                    "low_raw": stmt.excluded.low_raw,
                    "close_raw": stmt.excluded.close_raw,
                    "volume_raw": stmt.excluded.volume_raw,
                    "exchange": stmt.excluded.exchange,
                },
            )
            session.execute(stmt)

        self.logger.debug(
            "Upserted %d rows for %s (%s→%s)", len(rows), symbol, from_date, to_date
        )
        return len(rows)
