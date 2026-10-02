"""
FInsight Trading Engine — Data Quality Checker
===============================================
Validates the integrity and freshness of data stored in ``market_data_lake``.

This module is stateless and pure (no side effects beyond DB reads).  It is
safe to call at any point — from the EOD pipeline, CI tests, or ad-hoc audits.

Quality checks performed:
    1. **OHLCV integrity** (per symbol + date range):
       - Missing trading days versus the NSE holiday-aware calendar.
       - Zero-volume days (valid occasionally but suspicious if frequent).
       - OHLC relationship violations: ``low > high``, ``open > high``,
         ``close > high``, ``open < low``, ``close < low``.
       - Large day-over-day price gaps (> 20 % abs change in close).

    2. **Data staleness** (per symbol):
       - Checks that the most recent row is within ``max_lag_days`` trading
         days of today.

    3. **Universe-level quality report**:
       - Aggregates per-symbol summaries across all symbols in
         ``market_data_lake`` into a single dict for monitoring.

Usage:
    from data.quality_checker import DataQualityChecker
    from datetime import date

    checker = DataQualityChecker()
    warnings = checker.check_ohlcv_integrity("INFY", (date(2024,1,1), date(2024,12,31)))
    is_stale = checker.check_stale_data("INFY", max_lag_days=1)
    report = checker.get_universe_quality_report()
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy import text

from data.db.connection import get_session

logger = logging.getLogger(__name__)

# Path to strategy_config.yaml — two levels above this file (data/)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "strategy_config.yaml"

# NSE approximate holiday set — kept in sync with ohlcv_ingestor._NSE_HOLIDAY_SET
# (import to avoid duplication in production; duplicated here for clarity)
_NSE_HOLIDAYS: frozenset[date] = frozenset(
    [
        # 2024
        date(2024, 1, 22), date(2024, 2, 19), date(2024, 3, 25),
        date(2024, 3, 29), date(2024, 4, 11), date(2024, 4, 14),
        date(2024, 4, 17), date(2024, 4, 21), date(2024, 5, 23),
        date(2024, 6, 17), date(2024, 7, 17), date(2024, 8, 15),
        date(2024, 10, 2), date(2024, 11, 1), date(2024, 11, 15),
        date(2024, 12, 25),
        # 2025
        date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31),
        date(2025, 4, 10), date(2025, 4, 14), date(2025, 4, 18),
        date(2025, 5, 12), date(2025, 6, 7), date(2025, 7, 6),
        date(2025, 8, 15), date(2025, 8, 27), date(2025, 10, 2),
        date(2025, 10, 20), date(2025, 10, 21), date(2025, 11, 5),
        date(2025, 12, 25),
    ]
)

# Threshold for "suspiciously large" day-over-day price move
_LARGE_GAP_THRESHOLD_PCT = 20.0


def _load_config() -> dict:
    """
    Load and return ``strategy_config.yaml`` as a plain dict.

    Returns:
        Parsed YAML configuration dict.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"strategy_config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _get_nse_trading_days(from_date: date, to_date: date) -> list[date]:
    """
    Return expected NSE trading days in [from_date, to_date].

    A trading day is a weekday (Mon–Fri) that is not in the NSE holiday set.

    Args:
        from_date: Start date (inclusive).
        to_date: End date (inclusive).

    Returns:
        Sorted list of trading dates.
    """
    days = []
    current = from_date
    while current <= to_date:
        if current.weekday() < 5 and current not in _NSE_HOLIDAYS:
            days.append(current)
        current += timedelta(days=1)
    return days


class DataQualityChecker:
    """
    Validates OHLCV data integrity and freshness in ``market_data_lake``.

    All methods are read-only (no DB writes).  Safe to call concurrently.

    Args:
        None — config loaded from ``strategy_config.yaml``.
    """

    def __init__(self) -> None:
        self.config = _load_config()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_ohlcv_integrity(
        self, symbol: str, date_range: tuple[date, date]
    ) -> list[str]:
        """
        Validate OHLCV data for *symbol* over *date_range*.

        Checks performed (in order):
            1. Missing trading days (vs NSE calendar).
            2. Zero-volume days.
            3. OHLC relationship violations (e.g. ``low > high``).
            4. Suspiciously large day-over-day close gaps (> 20 %).

        Each violation generates a human-readable warning string in the
        returned list.  An empty list means no issues detected.

        Args:
            symbol: NSE ticker to check.
            date_range: Tuple of (start_date, end_date) inclusive.

        Returns:
            List of warning strings. Empty = clean data.
        """
        from_date, to_date = date_range
        self.logger.debug(
            "Checking OHLCV integrity for %s (%s → %s)", symbol, from_date, to_date
        )

        warnings: list[str] = []

        # Load OHLCV from DB
        df = self._load_ohlcv(symbol, from_date, to_date)

        if df.empty:
            warnings.append(
                f"[{symbol}] No OHLCV data found in range {from_date} → {to_date}."
            )
            return warnings

        # Normalise trade_date column to Python date objects
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.sort_values("trade_date").reset_index(drop=True)

        # ── Check 1: Missing trading days ─────────────────────────────
        expected_days = set(_get_nse_trading_days(from_date, to_date))
        actual_days = set(df["trade_date"].tolist())
        missing = sorted(expected_days - actual_days)
        for d in missing:
            warnings.append(
                f"[{symbol}] Missing trading day: {d} "
                f"(gap in NSE calendar not accounted for by holidays)"
            )

        # ── Check 2: Zero-volume days ─────────────────────────────────
        zero_vol_days = df[df["volume_raw"] == 0]["trade_date"].tolist()
        for d in zero_vol_days:
            warnings.append(
                f"[{symbol}] Zero volume on {d}. "
                "Possible data error or trading halt."
            )

        # ── Check 3: OHLC relationship violations ─────────────────────
        ohlc_violations = df[
            (df["low_raw"] > df["high_raw"])
            | (df["open_raw"] > df["high_raw"])
            | (df["close_raw"] > df["high_raw"])
            | (df["open_raw"] < df["low_raw"])
            | (df["close_raw"] < df["low_raw"])
        ]
        for _, row in ohlc_violations.iterrows():
            warnings.append(
                f"[{symbol}] OHLC violation on {row['trade_date']}: "
                f"O={row['open_raw']} H={row['high_raw']} "
                f"L={row['low_raw']} C={row['close_raw']}"
            )

        # ── Check 4: Large day-over-day price gaps ────────────────────
        if len(df) > 1:
            df["prev_close"] = df["close_raw"].shift(1)
            df["pct_change"] = (
                (df["close_raw"] - df["prev_close"]).abs() / df["prev_close"] * 100
            )
            large_gaps = df[df["pct_change"] > _LARGE_GAP_THRESHOLD_PCT].dropna()
            for _, row in large_gaps.iterrows():
                warnings.append(
                    f"[{symbol}] Large price gap on {row['trade_date']}: "
                    f"{row['pct_change']:.1f}% change "
                    f"(prev close={row['prev_close']:.2f}, "
                    f"current close={row['close_raw']:.2f}). "
                    "Possible split/adjustment needed or data error."
                )

        if warnings:
            self.logger.warning(
                "%d integrity issues found for %s.", len(warnings), symbol
            )
        else:
            self.logger.debug("No integrity issues for %s.", symbol)

        return warnings

    def check_stale_data(self, symbol: str, max_lag_days: int = 1) -> bool:
        """
        Return True if the most recent OHLCV row for *symbol* is older than
        *max_lag_days* trading days from today.

        A symbol with no data at all is considered stale.

        Args:
            symbol: NSE ticker to check.
            max_lag_days: Maximum allowed lag in trading days.  Default is 1
                (i.e., data must be from the most recent trading day).

        Returns:
            True if data is stale (too old or absent), False if fresh.
        """
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT MAX(trade_date) FROM market_data_lake WHERE symbol = :sym"
                ),
                {"sym": symbol},
            ).fetchone()

        if not row or row[0] is None:
            self.logger.warning("%s has no data — considered stale.", symbol)
            return True

        latest_date = (
            row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
        )

        # Count trading days between latest_date and today
        today = date.today()
        # Include latest_date itself when counting the gap window
        lag_window_start = latest_date + timedelta(days=1)
        trading_days_since = len(_get_nse_trading_days(lag_window_start, today))

        is_stale = trading_days_since > max_lag_days
        if is_stale:
            self.logger.warning(
                "%s data is stale: latest=%s, trading days lag=%d (max=%d).",
                symbol,
                latest_date,
                trading_days_since,
                max_lag_days,
            )
        else:
            self.logger.debug(
                "%s data is fresh: latest=%s, lag=%d trading day(s).",
                symbol,
                latest_date,
                trading_days_since,
            )
        return is_stale

    def get_universe_quality_report(self) -> dict[str, Any]:
        """
        Generate a quality summary report across all symbols in ``market_data_lake``.

        Returns aggregate statistics and per-symbol staleness flags.  This
        report is designed to be logged or displayed by the monitoring layer.

        Returns:
            Dict with the following structure::

                {
                    "generated_at": "2024-10-01",
                    "total_symbols": 150,
                    "stale_symbols": ["XYZCO", "ABCCO"],
                    "stale_count": 2,
                    "per_symbol": {
                        "INFY": {
                            "row_count": 252,
                            "min_date": "2023-10-02",
                            "max_date": "2024-09-30",
                            "is_stale": False,
                            "zero_volume_days": 0,
                        },
                        ...
                    },
                    "total_rows": 37800,
                    "symbols_with_gaps": ["SOMESTOCK"],
                    "symbols_with_ohlc_violations": [],
                }
        """
        self.logger.info("Generating universe quality report.")

        # ── Aggregate stats from DB ───────────────────────────────────
        with get_session() as session:
            summary_rows = session.execute(
                text(
                    """
                    SELECT
                        symbol,
                        COUNT(*) AS row_count,
                        MIN(trade_date) AS min_date,
                        MAX(trade_date) AS max_date,
                        SUM(CASE WHEN volume_raw = 0 THEN 1 ELSE 0 END) AS zero_vol_days
                    FROM market_data_lake
                    GROUP BY symbol
                    ORDER BY symbol
                    """
                )
            ).fetchall()

        total_rows_count = sum(r[1] for r in summary_rows)
        today = date.today()
        stale_symbols: list[str] = []
        symbols_with_gaps: list[str] = []
        symbols_with_violations: list[str] = []
        per_symbol: dict[str, Any] = {}

        for row in summary_rows:
            symbol, row_count, min_date_raw, max_date_raw, zero_vol_days = row
            min_dt = (
                min_date_raw
                if isinstance(min_date_raw, date)
                else date.fromisoformat(str(min_date_raw))
            )
            max_dt = (
                max_date_raw
                if isinstance(max_date_raw, date)
                else date.fromisoformat(str(max_date_raw))
            )

            # Staleness check (1 trading day lag tolerance)
            is_stale = self.check_stale_data(symbol, max_lag_days=1)
            if is_stale:
                stale_symbols.append(symbol)

            # Gap detection (approximate: compare row count to expected days)
            expected_count = len(_get_nse_trading_days(min_dt, max_dt))
            has_gaps = row_count < expected_count * 0.95  # Allow 5 % tolerance
            if has_gaps:
                symbols_with_gaps.append(symbol)

            # OHLC violation quick-check via integrity check on full range
            ohlc_warnings = [
                w for w in self.check_ohlcv_integrity(symbol, (min_dt, max_dt))
                if "OHLC violation" in w
            ]
            if ohlc_warnings:
                symbols_with_violations.append(symbol)

            per_symbol[symbol] = {
                "row_count": row_count,
                "min_date": str(min_dt),
                "max_date": str(max_dt),
                "is_stale": is_stale,
                "zero_volume_days": zero_vol_days or 0,
                "expected_trading_days": expected_count,
                "has_gaps": has_gaps,
                "ohlc_violation_count": len(ohlc_warnings),
            }

        report = {
            "generated_at": str(today),
            "total_symbols": len(summary_rows),
            "stale_symbols": stale_symbols,
            "stale_count": len(stale_symbols),
            "symbols_with_gaps": symbols_with_gaps,
            "symbols_with_ohlc_violations": symbols_with_violations,
            "total_rows": total_rows_count,
            "per_symbol": per_symbol,
        }

        self.logger.info(
            "Quality report: %d symbols, %d stale, %d with gaps, %d with OHLC violations.",
            len(summary_rows),
            len(stale_symbols),
            len(symbols_with_gaps),
            len(symbols_with_violations),
        )
        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_ohlcv(
        self, symbol: str, from_date: date, to_date: date
    ) -> pd.DataFrame:
        """
        Load OHLCV rows from ``market_data_lake`` for *symbol* and date range.

        Args:
            symbol: NSE ticker.
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            DataFrame with columns: trade_date, open_raw, high_raw, low_raw,
            close_raw, volume_raw.
        """
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT trade_date, open_raw, high_raw, low_raw,
                           close_raw, volume_raw
                    FROM market_data_lake
                    WHERE symbol = :sym
                      AND trade_date BETWEEN :start AND :end
                    ORDER BY trade_date ASC
                    """
                ),
                {"sym": symbol, "start": from_date, "end": to_date},
            ).fetchall()

        if not rows:
            return pd.DataFrame(
                columns=[
                    "trade_date", "open_raw", "high_raw",
                    "low_raw", "close_raw", "volume_raw",
                ]
            )

        return pd.DataFrame(
            rows,
            columns=["trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"],
        )
