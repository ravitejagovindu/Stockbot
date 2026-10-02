"""
Unit Tests — DataQualityChecker
================================
Tests for ``data/quality_checker.py``.

All tests use ``unittest.mock`` to patch DB access and the strategy config
loader.  No real database connections, no API calls.

Test coverage:
    - check_ohlcv_integrity():
        * Clean dataset returns empty warnings list
        * Missing trading days flagged correctly
        * Zero-volume days flagged
        * OHLC violations (low > high, open > high, close < low)
        * Large day-over-day price gaps (> 20 %)
        * No data for symbol returns single warning
    - check_stale_data():
        * Fresh data (latest row = yesterday's trading day) → False
        * Stale data (latest row > 1 trading day ago) → True
        * No data at all → True (stale)
    - get_universe_quality_report():
        * Returns correct structure with expected keys
        * Stale symbols correctly identified
        * Symbols with OHLC violations appear in report
        * Zero symbols (empty DB) returns zero counts
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd

# ---------------------------------------------------------------------------
# We patch _load_config and get_session before importing the module under test
# so that no real file I/O or DB connections are made during test collection.
# ---------------------------------------------------------------------------


class TestCheckOhlcvIntegrity(unittest.TestCase):
    """Tests for DataQualityChecker.check_ohlcv_integrity()."""

    def _make_checker(self):
        """
        Construct a DataQualityChecker with the config loader and DB session
        both mocked out.
        """
        with patch("data.quality_checker._load_config", return_value=self._mock_config()):
            from data.quality_checker import DataQualityChecker
            return DataQualityChecker()

    @staticmethod
    def _mock_config() -> dict:
        return {
            "data": {"adtv_sma_period": 20},
            "universe": {"min_market_cap_cr": 5000, "min_adtv_cr": 25},
        }

    def _make_clean_df(self, from_date: date, to_date: date) -> pd.DataFrame:
        """Build a clean OHLCV DataFrame for weekdays in the given range."""
        days = []
        current = from_date
        while current <= to_date:
            if current.weekday() < 5:  # Mon-Fri
                days.append(current)
            current += timedelta(days=1)

        return pd.DataFrame(
            {
                "trade_date": days,
                "open_raw": [100.0] * len(days),
                "high_raw": [105.0] * len(days),
                "low_raw": [95.0] * len(days),
                "close_raw": [102.0] * len(days),
                "volume_raw": [1_000_000] * len(days),
            }
        )

    @patch("data.quality_checker.get_session")
    @patch("data.quality_checker._load_config")
    def test_clean_data_no_warnings(self, mock_config, mock_get_session):
        """A perfectly clean dataset should produce zero warnings."""
        mock_config.return_value = self._mock_config()

        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        # Use a Monday-to-Friday week (no NSE holidays in this test week)
        from_date = date(2024, 9, 2)   # Monday
        to_date = date(2024, 9, 6)     # Friday
        clean_df = self._make_clean_df(from_date, to_date)

        with patch.object(checker, "_load_ohlcv", return_value=clean_df):
            warnings = checker.check_ohlcv_integrity("INFY", (from_date, to_date))

        self.assertEqual(
            warnings,
            [],
            f"Expected no warnings for clean data but got: {warnings}",
        )

    @patch("data.quality_checker._load_config")
    def test_missing_trading_day_flagged(self, mock_config):
        """Missing weekday in data should produce a 'Missing trading day' warning."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        from_date = date(2024, 9, 2)   # Mon
        to_date = date(2024, 9, 6)     # Fri
        # Remove Wednesday from the dataset
        full_df = self._make_clean_df(from_date, to_date)
        wednesday = date(2024, 9, 4)
        df_missing = full_df[full_df["trade_date"] != wednesday].copy()

        with patch.object(checker, "_load_ohlcv", return_value=df_missing):
            warnings = checker.check_ohlcv_integrity("INFY", (from_date, to_date))

        missing_warnings = [w for w in warnings if "Missing trading day" in w]
        self.assertEqual(len(missing_warnings), 1)
        self.assertIn(str(wednesday), missing_warnings[0])

    @patch("data.quality_checker._load_config")
    def test_zero_volume_flagged(self, mock_config):
        """A day with zero volume should generate a warning."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        from_date = date(2024, 9, 2)
        to_date = date(2024, 9, 6)
        df = self._make_clean_df(from_date, to_date)

        # Set volume to 0 on Tuesday
        tuesday = date(2024, 9, 3)
        df.loc[df["trade_date"] == tuesday, "volume_raw"] = 0

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("INFY", (from_date, to_date))

        zero_vol_warnings = [w for w in warnings if "Zero volume" in w]
        self.assertEqual(len(zero_vol_warnings), 1)
        self.assertIn(str(tuesday), zero_vol_warnings[0])

    @patch("data.quality_checker._load_config")
    def test_ohlc_low_greater_than_high(self, mock_config):
        """low > high is an OHLC violation and should be flagged."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        from_date = date(2024, 9, 2)
        to_date = date(2024, 9, 2)
        df = pd.DataFrame(
            {
                "trade_date": [from_date],
                "open_raw": [100.0],
                "high_raw": [95.0],   # ← high < low: violation
                "low_raw": [98.0],
                "close_raw": [97.0],
                "volume_raw": [500_000],
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("TEST", (from_date, to_date))

        ohlc_warnings = [w for w in warnings if "OHLC violation" in w]
        self.assertGreaterEqual(len(ohlc_warnings), 1)

    @patch("data.quality_checker._load_config")
    def test_ohlc_close_below_low(self, mock_config):
        """close < low is an OHLC violation."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d = date(2024, 9, 2)
        df = pd.DataFrame(
            {
                "trade_date": [d],
                "open_raw": [100.0],
                "high_raw": [105.0],
                "low_raw": [96.0],
                "close_raw": [90.0],   # ← close < low: violation
                "volume_raw": [500_000],
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("TEST", (d, d))

        ohlc_warnings = [w for w in warnings if "OHLC violation" in w]
        self.assertGreaterEqual(len(ohlc_warnings), 1)

    @patch("data.quality_checker._load_config")
    def test_ohlc_open_above_high(self, mock_config):
        """open > high is an OHLC violation."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d = date(2024, 9, 2)
        df = pd.DataFrame(
            {
                "trade_date": [d],
                "open_raw": [110.0],   # ← open > high: violation
                "high_raw": [105.0],
                "low_raw": [96.0],
                "close_raw": [100.0],
                "volume_raw": [500_000],
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("TEST", (d, d))

        ohlc_warnings = [w for w in warnings if "OHLC violation" in w]
        self.assertGreaterEqual(len(ohlc_warnings), 1)

    @patch("data.quality_checker._load_config")
    def test_large_price_gap_flagged(self, mock_config):
        """A day-over-day close change > 20% should trigger a large gap warning."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d1 = date(2024, 9, 2)
        d2 = date(2024, 9, 3)
        df = pd.DataFrame(
            {
                "trade_date": [d1, d2],
                "open_raw": [100.0, 130.0],
                "high_raw": [105.0, 135.0],
                "low_raw": [98.0, 125.0],
                "close_raw": [100.0, 130.0],  # ← 30% gap: should flag
                "volume_raw": [1_000_000, 1_200_000],
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("TEST", (d1, d2))

        gap_warnings = [w for w in warnings if "Large price gap" in w]
        self.assertEqual(len(gap_warnings), 1)
        self.assertIn("30.0%", gap_warnings[0])

    @patch("data.quality_checker._load_config")
    def test_gap_below_threshold_not_flagged(self, mock_config):
        """A 10% gap is below threshold and should NOT produce a gap warning."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d1 = date(2024, 9, 2)
        d2 = date(2024, 9, 3)
        df = pd.DataFrame(
            {
                "trade_date": [d1, d2],
                "open_raw": [100.0, 110.0],
                "high_raw": [105.0, 112.0],
                "low_raw": [98.0, 108.0],
                "close_raw": [100.0, 110.0],  # ← 10% gap: should NOT flag
                "volume_raw": [1_000_000, 1_200_000],
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("TEST", (d1, d2))

        gap_warnings = [w for w in warnings if "Large price gap" in w]
        self.assertEqual(len(gap_warnings), 0)

    @patch("data.quality_checker._load_config")
    def test_no_data_returns_single_warning(self, mock_config):
        """An empty DataFrame should produce exactly one 'No OHLCV data' warning."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d = date(2024, 9, 2)
        empty_df = pd.DataFrame(
            columns=["trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"]
        )

        with patch.object(checker, "_load_ohlcv", return_value=empty_df):
            warnings = checker.check_ohlcv_integrity("GHOST", (d, d))

        self.assertEqual(len(warnings), 1)
        self.assertIn("No OHLCV data", warnings[0])

    @patch("data.quality_checker._load_config")
    def test_multiple_violations_all_reported(self, mock_config):
        """Multiple distinct violations in one dataset should all be captured."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d1 = date(2024, 9, 2)
        d2 = date(2024, 9, 3)
        df = pd.DataFrame(
            {
                "trade_date": [d1, d2],
                "open_raw": [100.0, 200.0],   # d2 open > high (violation)
                "high_raw": [105.0, 195.0],   # d2 high < open
                "low_raw": [98.0, 190.0],
                "close_raw": [100.0, 200.0],  # d2 close > high (violation) + 100% gap
                "volume_raw": [1_000_000, 0],  # d2 zero volume
            }
        )

        with patch.object(checker, "_load_ohlcv", return_value=df):
            warnings = checker.check_ohlcv_integrity("BAD", (d1, d2))

        warning_types = set()
        for w in warnings:
            if "Zero volume" in w:
                warning_types.add("zero_vol")
            if "OHLC violation" in w:
                warning_types.add("ohlc")
            if "Large price gap" in w:
                warning_types.add("gap")

        self.assertIn("zero_vol", warning_types)
        self.assertIn("ohlc", warning_types)
        self.assertIn("gap", warning_types)


class TestCheckStaleData(unittest.TestCase):
    """Tests for DataQualityChecker.check_stale_data()."""

    @staticmethod
    def _mock_config() -> dict:
        return {"data": {}, "universe": {}}

    def _make_checker(self):
        with patch("data.quality_checker._load_config", return_value=self._mock_config()):
            from data.quality_checker import DataQualityChecker
            return DataQualityChecker()

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_fresh_data_not_stale(self, mock_get_session, mock_config):
        """Data from the most recent trading day should not be stale."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        # Simulate latest_date = yesterday (assuming yesterday was a trading day)
        # We'll patch check_stale_data's internal DB call
        yesterday = date.today() - timedelta(days=1)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchone.return_value = (str(yesterday),)
        mock_get_session.return_value = mock_ctx

        # Patch _get_nse_trading_days so lag = 0 even if yesterday was holiday
        with patch("data.quality_checker._get_nse_trading_days", return_value=[]):
            result = checker.check_stale_data("INFY", max_lag_days=1)

        # 0 trading days of lag ≤ 1: not stale
        self.assertFalse(result)

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_no_data_is_stale(self, mock_get_session, mock_config):
        """Symbol with no rows at all must be reported as stale."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        # Simulate MAX(trade_date) = NULL
        mock_ctx.execute.return_value.fetchone.return_value = (None,)
        mock_get_session.return_value = mock_ctx

        result = checker.check_stale_data("GHOST", max_lag_days=1)
        self.assertTrue(result)

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_old_data_is_stale(self, mock_get_session, mock_config):
        """Data from 5 trading days ago should be stale with max_lag_days=1."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        # Simulate latest_date = 10 calendar days ago (covers ~5 trading days)
        old_date = date.today() - timedelta(days=10)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchone.return_value = (str(old_date),)
        mock_get_session.return_value = mock_ctx

        # Patch _get_nse_trading_days to return 5 days in the lag window
        five_days = [old_date + timedelta(days=i) for i in range(1, 6)]
        with patch("data.quality_checker._get_nse_trading_days", return_value=five_days):
            result = checker.check_stale_data("STALE", max_lag_days=1)

        # 5 trading days of lag > 1: stale
        self.assertTrue(result)

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_custom_max_lag_honoured(self, mock_get_session, mock_config):
        """max_lag_days=3 should allow up to 3 trading days of lag."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        # Simulate latest_date = 3 trading days ago
        old_date = date.today() - timedelta(days=5)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchone.return_value = (str(old_date),)
        mock_get_session.return_value = mock_ctx

        # 3 trading days of lag
        three_days = [old_date + timedelta(days=i) for i in range(1, 4)]
        with patch("data.quality_checker._get_nse_trading_days", return_value=three_days):
            result = checker.check_stale_data("SEMI_FRESH", max_lag_days=3)

        # 3 lag == 3 max: not stale (boundary condition)
        self.assertFalse(result)

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_lag_exceeds_custom_max(self, mock_get_session, mock_config):
        """4 trading days of lag with max_lag_days=3 → stale."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        old_date = date.today() - timedelta(days=7)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchone.return_value = (str(old_date),)
        mock_get_session.return_value = mock_ctx

        four_days = [old_date + timedelta(days=i) for i in range(1, 5)]
        with patch("data.quality_checker._get_nse_trading_days", return_value=four_days):
            result = checker.check_stale_data("TOO_OLD", max_lag_days=3)

        # 4 lag > 3 max: stale
        self.assertTrue(result)


class TestGetUniverseQualityReport(unittest.TestCase):
    """Tests for DataQualityChecker.get_universe_quality_report()."""

    @staticmethod
    def _mock_config() -> dict:
        return {"data": {}, "universe": {}}

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_empty_db_returns_zero_counts(self, mock_get_session, mock_config):
        """An empty market_data_lake should return a report with zero symbols."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchall.return_value = []  # empty DB
        mock_get_session.return_value = mock_ctx

        report = checker.get_universe_quality_report()

        self.assertEqual(report["total_symbols"], 0)
        self.assertEqual(report["stale_count"], 0)
        self.assertEqual(report["total_rows"], 0)
        self.assertEqual(report["stale_symbols"], [])
        self.assertEqual(report["per_symbol"], {})

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_report_structure_keys_present(self, mock_get_session, mock_config):
        """Report dict must contain all expected top-level keys."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchall.return_value = []
        mock_get_session.return_value = mock_ctx

        report = checker.get_universe_quality_report()

        required_keys = {
            "generated_at",
            "total_symbols",
            "stale_symbols",
            "stale_count",
            "symbols_with_gaps",
            "symbols_with_ohlc_violations",
            "total_rows",
            "per_symbol",
        }
        self.assertEqual(required_keys, set(report.keys()))

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_stale_symbol_appears_in_stale_list(self, mock_get_session, mock_config):
        """A symbol with old data must appear in stale_symbols list."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        old_date = date(2020, 1, 1)
        today = date.today()

        # Summary row: (symbol, row_count, min_date, max_date, zero_vol_days)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchall.return_value = [
            ("STALE_CO", 100, str(old_date), str(old_date), 0)
        ]
        mock_get_session.return_value = mock_ctx

        # Patch sub-methods so the per-symbol integrity check doesn't hit DB again
        with patch.object(checker, "check_stale_data", return_value=True), \
             patch.object(checker, "check_ohlcv_integrity", return_value=[]):
            report = checker.get_universe_quality_report()

        self.assertIn("STALE_CO", report["stale_symbols"])
        self.assertEqual(report["stale_count"], 1)
        self.assertTrue(report["per_symbol"]["STALE_CO"]["is_stale"])

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_ohlc_violation_symbol_appears_in_list(self, mock_get_session, mock_config):
        """A symbol with OHLC violations must appear in symbols_with_ohlc_violations."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d = date(2024, 9, 2)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.execute.return_value.fetchall.return_value = [
            ("BAD_CO", 1, str(d), str(d), 0)
        ]
        mock_get_session.return_value = mock_ctx

        with patch.object(checker, "check_stale_data", return_value=False), \
             patch.object(
                 checker,
                 "check_ohlcv_integrity",
                 return_value=["[BAD_CO] OHLC violation on 2024-09-02: O=110 H=105 L=98 C=97"],
             ):
            report = checker.get_universe_quality_report()

        self.assertIn("BAD_CO", report["symbols_with_ohlc_violations"])
        self.assertEqual(report["per_symbol"]["BAD_CO"]["ohlc_violation_count"], 1)

    @patch("data.quality_checker._load_config")
    @patch("data.quality_checker.get_session")
    def test_total_rows_summed_correctly(self, mock_get_session, mock_config):
        """total_rows should be the sum of row_count across all symbols."""
        mock_config.return_value = self._mock_config()
        from data.quality_checker import DataQualityChecker

        checker = DataQualityChecker()

        d = date(2024, 9, 2)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        # Two symbols with 100 and 200 rows respectively
        mock_ctx.execute.return_value.fetchall.return_value = [
            ("SYM_A", 100, str(d), str(d), 0),
            ("SYM_B", 200, str(d), str(d), 0),
        ]
        mock_get_session.return_value = mock_ctx

        with patch.object(checker, "check_stale_data", return_value=False), \
             patch.object(checker, "check_ohlcv_integrity", return_value=[]):
            report = checker.get_universe_quality_report()

        self.assertEqual(report["total_rows"], 300)
        self.assertEqual(report["total_symbols"], 2)


class TestParseRatio(unittest.TestCase):
    """Unit tests for the parse_ratio utility in corporate_actions_ingestor."""

    def setUp(self):
        # Import inside setUp so mocks in other test classes don't interfere
        from data.ingestion.corporate_actions_ingestor import parse_ratio
        self.parse_ratio = parse_ratio

    def test_standard_split_ratio(self):
        """'1:2' parses to (1.0, 2.0)."""
        num, den = self.parse_ratio("1:2")
        self.assertEqual(num, 1.0)
        self.assertEqual(den, 2.0)

    def test_bonus_ratio(self):
        """'1:5' parses to (1.0, 5.0)."""
        num, den = self.parse_ratio("1:5")
        self.assertEqual(num, 1.0)
        self.assertEqual(den, 5.0)

    def test_ratio_with_whitespace(self):
        """'1 : 2' (with spaces) parses correctly."""
        num, den = self.parse_ratio("1 : 2")
        self.assertEqual(num, 1.0)
        self.assertEqual(den, 2.0)

    def test_decimal_ratio(self):
        """'1.5:2.0' parses correctly."""
        num, den = self.parse_ratio("1.5:2.0")
        self.assertAlmostEqual(num, 1.5)
        self.assertAlmostEqual(den, 2.0)

    def test_invalid_string_returns_none_none(self):
        """Non-ratio string returns (None, None)."""
        num, den = self.parse_ratio("invalid")
        self.assertIsNone(num)
        self.assertIsNone(den)

    def test_empty_string_returns_none_none(self):
        """Empty string returns (None, None)."""
        num, den = self.parse_ratio("")
        self.assertIsNone(num)
        self.assertIsNone(den)

    def test_none_returns_none_none(self):
        """None input returns (None, None)."""
        num, den = self.parse_ratio(None)
        self.assertIsNone(num)
        self.assertIsNone(den)

    def test_five_for_one_split(self):
        """'5:1' (5 new for 1 old) parses to (5.0, 1.0)."""
        num, den = self.parse_ratio("5:1")
        self.assertEqual(num, 5.0)
        self.assertEqual(den, 1.0)


class TestNSETradingDays(unittest.TestCase):
    """Unit tests for the NSE trading day helper."""

    @patch("data.quality_checker._load_config")
    def test_weekends_excluded(self, mock_config):
        """Saturday and Sunday should not appear in trading days."""
        mock_config.return_value = {"data": {}, "universe": {}}
        from data.quality_checker import _get_nse_trading_days

        # Full week Mon 2 Sep to Sun 8 Sep 2024
        days = _get_nse_trading_days(date(2024, 9, 2), date(2024, 9, 8))
        for d in days:
            self.assertLess(
                d.weekday(), 5, f"{d} ({d.strftime('%A')}) should not be a trading day"
            )

    @patch("data.quality_checker._load_config")
    def test_known_holiday_excluded(self, mock_config):
        """A known NSE holiday (2024-08-15 Independence Day) must not be in the list."""
        mock_config.return_value = {"data": {}, "universe": {}}
        from data.quality_checker import _get_nse_trading_days

        independence_day = date(2024, 8, 15)
        days = _get_nse_trading_days(date(2024, 8, 12), date(2024, 8, 16))
        self.assertNotIn(independence_day, days)

    @patch("data.quality_checker._load_config")
    def test_regular_weekday_included(self, mock_config):
        """A regular Monday (not a holiday) must be in the trading days list."""
        mock_config.return_value = {"data": {}, "universe": {}}
        from data.quality_checker import _get_nse_trading_days

        # 2024-09-02 is a Monday and not an NSE holiday
        regular_monday = date(2024, 9, 2)
        days = _get_nse_trading_days(date(2024, 9, 2), date(2024, 9, 2))
        self.assertIn(regular_monday, days)

    @patch("data.quality_checker._load_config")
    def test_empty_range_returns_empty_list(self, mock_config):
        """from_date > to_date should return an empty list."""
        mock_config.return_value = {"data": {}, "universe": {}}
        from data.quality_checker import _get_nse_trading_days

        days = _get_nse_trading_days(date(2024, 9, 6), date(2024, 9, 2))
        self.assertEqual(days, [])


if __name__ == "__main__":
    unittest.main()
