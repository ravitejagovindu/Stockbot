"""
Unit tests for engine_core.indicators — pure functions only.

All tests use known numerical values computed by hand or cross-checked against
TradingView's ta.sma / ta.atr / ta.lowest / ta.highest functions.

No database, no fixtures, no mocks required — pure Series in, Series out.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from engine_core.indicators import atr, donchian_high, donchian_low, rma, sma


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_series(*values, name=None):
    """Convenience: build a pd.Series from positional float args."""
    return pd.Series(list(values), dtype=float, name=name)


# ===========================================================================
# SMA tests
# ===========================================================================

class TestSMA:
    """Tests for the simple moving average function."""

    def test_known_last_value(self):
        """SMA([1,2,3,4,5], period=3) → last value should be 4.0."""
        s = make_series(1, 2, 3, 4, 5)
        result = sma(s, 3)
        assert result.iloc[-1] == pytest.approx(4.0)

    def test_first_two_are_nan_for_period_3(self):
        """First period-1 values must be NaN (insufficient history)."""
        s = make_series(1, 2, 3, 4, 5)
        result = sma(s, 3)
        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])

    def test_third_value_for_period_3(self):
        """SMA of first three elements of [1,2,3,4,5] with period=3 should be 2.0."""
        s = make_series(1, 2, 3, 4, 5)
        result = sma(s, 3)
        assert result.iloc[2] == pytest.approx(2.0)

    def test_period_1_returns_self(self):
        """SMA with period=1 should equal the original series."""
        s = make_series(10, 20, 30)
        result = sma(s, 1)
        pd.testing.assert_series_equal(result, s, check_names=False)

    def test_period_equals_length_returns_single_value(self):
        """SMA with period equal to series length should return one non-NaN value."""
        s = make_series(2, 4, 6, 8)
        result = sma(s, 4)
        assert sum(~result.isna()) == 1
        assert result.iloc[-1] == pytest.approx(5.0)

    def test_invalid_period_raises(self):
        """Non-positive period should raise ValueError."""
        s = make_series(1, 2, 3)
        with pytest.raises(ValueError):
            sma(s, 0)
        with pytest.raises(ValueError):
            sma(s, -1)

    def test_index_preserved(self):
        """Output index must be identical to input index."""
        idx = pd.date_range("2024-01-01", periods=5)
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], index=idx)
        result = sma(s, 2)
        pd.testing.assert_index_equal(result.index, idx)


# ===========================================================================
# RMA tests
# ===========================================================================

class TestRMA:
    """Tests for Wilder's RMA smoothing."""

    def test_rma_first_period_minus_1_is_nan(self):
        """Values before the seed position must be NaN."""
        s = make_series(*range(1, 21))  # 20 values
        result = rma(s, 14)
        # First 13 should be NaN (positions 0..12)
        assert all(math.isnan(result.iloc[i]) for i in range(13))

    def test_rma_seed_is_simple_average(self):
        """The seed (first non-NaN) value must equal the SMA of the first `period` bars."""
        period = 5
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
        s = make_series(*values)
        result = rma(s, period)
        expected_seed = sum(values[:period]) / period  # 30.0
        assert result.iloc[period - 1] == pytest.approx(expected_seed)

    def test_rma_recurrence(self):
        """Next value after seed: alpha × current + (1-alpha) × prev."""
        period = 5
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        s = make_series(*values)
        result = rma(s, period)
        alpha = 1.0 / period
        seed = sum(values[:period]) / period  # 30.0
        expected_next = alpha * values[period] + (1 - alpha) * seed
        assert result.iloc[period] == pytest.approx(expected_next)

    def test_rma_invalid_period_raises(self):
        with pytest.raises(ValueError):
            rma(make_series(1, 2, 3), 0)


# ===========================================================================
# ATR tests
# ===========================================================================

class TestATR:
    """Tests for Average True Range with Wilder's smoothing."""

    def _flat_ohlcv(self, n=30, high=110.0, low=90.0, close=100.0):
        """Build OHLCV Series for flat prices (constant ATR)."""
        h = pd.Series([high] * n, dtype=float)
        lo = pd.Series([low] * n, dtype=float)
        c = pd.Series([close] * n, dtype=float)
        return h, lo, c

    def test_flat_prices_atr_equals_hl_range(self):
        """With constant prices, ATR should stabilise at (high - low)."""
        high, low, close = self._flat_ohlcv(n=30)
        result = atr(high, low, close, period=14)
        # After 14+5 bars the RMA should be converging to 20.0
        # For perfectly flat prices, seed = 20 and every update keeps it at 20
        assert result.iloc[-1] == pytest.approx(20.0, rel=1e-6)

    def test_atr_first_13_are_nan_for_period_14(self):
        """First 13 values (indices 0–12) must be NaN with period=14."""
        high, low, close = self._flat_ohlcv(n=20)
        result = atr(high, low, close, period=14)
        for i in range(13):
            assert math.isnan(result.iloc[i])

    def test_atr_nonnegative(self):
        """ATR should always be non-negative."""
        np.random.seed(42)
        prices = 100 + np.random.randn(60).cumsum()
        c = pd.Series(prices)
        h = c + np.abs(np.random.randn(60))
        lo = c - np.abs(np.random.randn(60))
        result = atr(h, lo, c, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_atr_default_period_14(self):
        """Default period argument should be 14."""
        import inspect
        sig = inspect.signature(atr)
        assert sig.parameters["period"].default == 14

    def test_atr_invalid_period_raises(self):
        high, low, close = self._flat_ohlcv(n=20)
        with pytest.raises(ValueError):
            atr(high, low, close, period=0)

    def test_atr_index_preserved(self):
        """ATR output index must match the close index."""
        idx = pd.date_range("2024-01-01", periods=30)
        c = pd.Series([100.0] * 30, index=idx)
        h = c + 5
        lo = c - 5
        result = atr(h, lo, c, period=14)
        pd.testing.assert_index_equal(result.index, idx)


# ===========================================================================
# Donchian Low tests
# ===========================================================================

class TestDonchianLow:
    """Tests for the rolling minimum (Donchian lower band)."""

    def test_known_value(self):
        """donchian_low([10,9,8,11,7], period=3) last value should be 7.0."""
        lows = make_series(10, 9, 8, 11, 7)
        result = donchian_low(lows, period=3)
        assert result.iloc[-1] == pytest.approx(7.0)

    def test_first_period_minus_1_nan(self):
        """First period-1 values must be NaN."""
        lows = make_series(10, 9, 8, 11, 7)
        result = donchian_low(lows, period=3)
        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])

    def test_rolling_minimum_correctness(self):
        """Verify each non-NaN value equals the rolling minimum."""
        lows = make_series(5, 4, 3, 6, 2, 8, 1)
        period = 3
        result = donchian_low(lows, period=period)
        for i in range(period - 1, len(lows)):
            expected = min(lows.iloc[i - period + 1 : i + 1])
            assert result.iloc[i] == pytest.approx(expected)

    def test_default_period_is_20(self):
        """Default period should be 20."""
        import inspect
        assert inspect.signature(donchian_low).parameters["period"].default == 20

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            donchian_low(make_series(1, 2, 3), 0)


# ===========================================================================
# Donchian High tests
# ===========================================================================

class TestDonchianHigh:
    """Tests for the rolling maximum (Donchian upper band)."""

    def test_known_value(self):
        """donchian_high([100,110,105,115,120], period=3) last value should be 120.0."""
        highs = make_series(100, 110, 105, 115, 120)
        result = donchian_high(highs, period=3)
        assert result.iloc[-1] == pytest.approx(120.0)

    def test_first_period_minus_1_nan(self):
        """First period-1 values must be NaN."""
        highs = make_series(100, 120, 110, 115, 105)
        result = donchian_high(highs, period=3)
        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])

    def test_rolling_maximum_correctness(self):
        """Verify each non-NaN value equals the rolling maximum."""
        highs = make_series(5, 10, 3, 15, 7, 20, 8)
        period = 3
        result = donchian_high(highs, period=period)
        for i in range(period - 1, len(highs)):
            expected = max(highs.iloc[i - period + 1 : i + 1])
            assert result.iloc[i] == pytest.approx(expected)

    def test_default_period_is_252(self):
        """Default period should be 252 (one trading year)."""
        import inspect
        assert inspect.signature(donchian_high).parameters["period"].default == 252

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            donchian_high(make_series(1, 2, 3), -5)
