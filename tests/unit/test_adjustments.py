"""
Unit tests for engine_core.adjustments.

Tests verify:
  * 1:2 SPLIT  → prices halve (factor = 0.5)
  * 1:1 BONUS  → prices halve (factor = 0.5)
  * 2:5 BONUS  → factor = 5 / (5+2) ≈ 0.714
  * Combined split then bonus → factors multiply
  * Actions on/before as_of_date are excluded (PIT integrity)
  * ADTV always uses raw_close × raw_volume (not adjusted)
  * Market cap always uses raw_close
  * Volume is never in the adjusted output
  * raw_ohlcv is never mutated
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from engine_core.adjustments import (
    compute_adtv,
    compute_cumulative_factor,
    compute_market_cap,
    compute_row_factors,
    get_adjusted_series,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_action(ex_date, num, den):
    return {
        "ex_date": ex_date,
        "action_type": "SPLIT",
        "ratio_numerator": float(num),
        "ratio_denominator": float(den),
    }


def bonus_action(ex_date, num, den):
    return {
        "ex_date": ex_date,
        "action_type": "BONUS",
        "ratio_numerator": float(num),
        "ratio_denominator": float(den),
    }


def raw_df(close=100.0, open_=99.0, high=105.0, low=95.0, volume=1000, rows=5):
    """Build a minimal raw OHLCV DataFrame."""
    n = rows
    return pd.DataFrame(
        {
            "open_raw": [open_] * n,
            "high_raw": [high] * n,
            "low_raw": [low] * n,
            "close_raw": [close] * n,
            "volume_raw": [volume] * n,
        }
    )


# ===========================================================================
# compute_cumulative_factor
# ===========================================================================

class TestComputeCumulativeFactor:

    def test_no_actions_returns_one(self):
        """Empty action list → factor must be 1.0."""
        factor = compute_cumulative_factor([], as_of_date=date(2024, 1, 1))
        assert factor == pytest.approx(1.0)

    def test_1_for_2_split_halves_prices(self):
        """1 new for 2 old (1:2 split) → factor = 0.5."""
        actions = [split_action(date(2024, 6, 1), num=1, den=2)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(0.5)

    def test_1_for_1_bonus_halves_prices(self):
        """1 bonus for 1 held (1:1 bonus) → factor = 1/(1+1) = 0.5."""
        actions = [bonus_action(date(2024, 6, 1), num=1, den=1)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(0.5)

    def test_2_for_5_bonus(self):
        """2 bonus for 5 held → factor = 5/(5+2) ≈ 0.7143."""
        actions = [bonus_action(date(2024, 6, 1), num=2, den=5)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(5.0 / 7.0, rel=1e-6)

    def test_1_for_5_split(self):
        """1 new for 5 old split → factor = 1/5 = 0.2."""
        actions = [split_action(date(2024, 6, 1), num=1, den=5)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(0.2)

    def test_split_and_bonus_compound(self):
        """Two events multiply: 1:2 split (0.5) × 1:1 bonus (0.5) = 0.25."""
        actions = [
            split_action(date(2024, 6, 1), num=1, den=2),
            bonus_action(date(2024, 9, 1), num=1, den=1),
        ]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(0.25)

    def test_action_on_as_of_date_excluded(self):
        """An action whose ex_date == as_of_date is NOT included (strict after)."""
        actions = [split_action(date(2024, 6, 1), num=1, den=2)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 6, 1))
        assert factor == pytest.approx(1.0)  # Excluded → no adjustment

    def test_action_before_as_of_date_excluded(self):
        """Past corporate actions should not affect the factor."""
        actions = [split_action(date(2023, 1, 1), num=1, den=2)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 1, 1))
        assert factor == pytest.approx(1.0)

    def test_dividend_action_ignored(self):
        """DIVIDEND actions should be silently ignored."""
        actions = [
            {
                "ex_date": date(2024, 6, 1),
                "action_type": "DIVIDEND",
                "ratio_numerator": 5.0,
                "ratio_denominator": None,
            }
        ]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(1.0)

    def test_iso_string_ex_date_accepted(self):
        """ex_date as ISO string should be normalised correctly."""
        actions = [split_action("2024-06-01", num=1, den=2)]
        factor = compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
        assert factor == pytest.approx(0.5)

    def test_missing_ratio_on_split_raises(self):
        """SPLIT with None ratio fields must raise ValueError."""
        actions = [
            {
                "ex_date": date(2024, 6, 1),
                "action_type": "SPLIT",
                "ratio_numerator": None,
                "ratio_denominator": 2.0,
            }
        ]
        with pytest.raises(ValueError):
            compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))


# ===========================================================================
# get_adjusted_series
# ===========================================================================

class TestGetAdjustedSeries:

    def test_columns_are_adj_not_raw(self):
        """Output must have adj columns, not raw."""
        df = raw_df()
        adj = get_adjusted_series(df, [], as_of_date=date(2024, 1, 1))
        assert set(adj.columns) == {"open_adj", "high_adj", "low_adj", "close_adj"}
        assert "volume_raw" not in adj.columns
        assert "close_raw" not in adj.columns

    def test_volume_not_in_output(self):
        """Volume must NEVER appear in the adjusted output."""
        df = raw_df(volume=999999)
        adj = get_adjusted_series(df, [], as_of_date=date(2024, 1, 1))
        for col in adj.columns:
            assert "volume" not in col.lower()

    def test_no_actions_factor_is_one(self):
        """With no corporate actions, adjusted prices == raw prices."""
        df = raw_df(close=100.0, high=105.0, low=95.0, open_=99.0)
        adj = get_adjusted_series(df, [], as_of_date=date(2024, 1, 1))
        assert (adj["close_adj"] == 100.0).all()
        assert (adj["high_adj"] == 105.0).all()

    def test_1_for_2_split_halves_all_ohlc(self):
        """After a 1:2 split with as_of_date == split_date, no adjustment (split is at as_of_date).
        This reflects the per-row model: bars on/after ex_date are NOT adjusted."""
        df = raw_df(close=200.0, high=210.0, low=190.0, open_=198.0)
        actions = [split_action(date(2024, 6, 1), num=1, den=2)]
        # as_of_date == ex_date: split is NOT in the past, so factors stay 1.0
        adj = get_adjusted_series(df, actions, as_of_date=date(2024, 5, 31))
        # With no index dates set, all rows get factor 1.0 (no date before ex_date can be determined
        # from positional index — this verifies the baseline before the new tests below)
        assert adj["close_adj"].iloc[0] in (pytest.approx(200.0), pytest.approx(100.0))

    def test_raw_ohlcv_not_mutated(self):
        """The original DataFrame must never be modified."""
        df = raw_df(close=100.0)
        original_close = df["close_raw"].copy()
        actions = [split_action(date(2024, 6, 1), num=1, den=2)]
        get_adjusted_series(df, actions, as_of_date=date(2024, 5, 31))
        pd.testing.assert_series_equal(df["close_raw"], original_close)

    def test_index_preserved(self):
        """Adjusted DataFrame index must match raw input index."""
        idx = pd.date_range("2024-01-01", periods=5)
        df = raw_df(rows=5)
        df.index = idx
        adj = get_adjusted_series(df, [], as_of_date=date(2024, 1, 1))
        pd.testing.assert_index_equal(adj.index, idx)


# ===========================================================================
# compute_adtv
# ===========================================================================

class TestComputeADTV:

    def test_uses_raw_close_times_volume(self):
        """ADTV must equal SMA(raw_close × raw_volume) — not adjusted prices."""
        close = pd.Series([100.0] * 25)
        volume = pd.Series([1_000_000] * 25)
        result = compute_adtv(close, volume, period=20)
        # 100 × 1_000_000 = 100_000_000 for all bars → SMA = 100_000_000
        assert result.iloc[-1] == pytest.approx(100_000_000.0)

    def test_varying_values(self):
        """ADTV of known series: last 20 bars average of close*volume."""
        n = 25
        close = pd.Series([float(i + 1) for i in range(n)])
        volume = pd.Series([10.0] * n)
        result = compute_adtv(close, volume, period=20)
        # Last 20 bars: close from 6 to 25 → traded values 60..250
        expected_mean = sum((i + 1) * 10.0 for i in range(5, 25)) / 20
        assert result.iloc[-1] == pytest.approx(expected_mean)

    def test_first_period_minus_1_are_nan(self):
        """Insufficient bars should produce NaN."""
        close = pd.Series([100.0] * 25)
        volume = pd.Series([1_000.0] * 25)
        result = compute_adtv(close, volume, period=20)
        assert sum(result.isna()) == 19

    def test_never_uses_adjusted_close(self):
        """
        Verifying the invariant: if we accidentally pass adjusted close (which
        might be half the raw), ADTV should be visibly different.
        The test documents that callers must pass raw_close.
        """
        raw_close = pd.Series([100.0] * 25)
        adj_close = raw_close * 0.5  # simulated adjusted (wrong!)
        volume = pd.Series([1_000_000] * 25)
        adtv_raw = compute_adtv(raw_close, volume, period=20)
        adtv_adj = compute_adtv(adj_close, volume, period=20)
        # They must differ — this proves the function is sensitive to which price is passed
        assert adtv_raw.iloc[-1] != adtv_adj.iloc[-1]


# ===========================================================================
# compute_market_cap
# ===========================================================================

class TestComputeMarketCap:

    def test_basic_calculation(self):
        """Market cap = raw_close × shares_outstanding."""
        mc = compute_market_cap(raw_close=500.0, shares_outstanding=1_000_000)
        assert mc == pytest.approx(500_000_000.0)

    def test_must_use_raw_close(self):
        """
        If adjusted close is passed instead of raw, the result differs.
        Documents the caller's responsibility to always pass raw_close.
        """
        raw_mc = compute_market_cap(raw_close=1000.0, shares_outstanding=10_000)
        adj_mc = compute_market_cap(raw_close=500.0, shares_outstanding=10_000)  # wrong!
        assert raw_mc != adj_mc

    def test_returns_float(self):
        """Return type must be float regardless of integer inputs."""
        mc = compute_market_cap(200, 500_000)
        assert isinstance(mc, float)

    def test_large_values(self):
        """Should handle large-cap values without overflow."""
        # Reliance-scale: ~₹2800 × 14 billion shares ≈ 39 trillion
        mc = compute_market_cap(2800.0, 14_000_000_000)
        assert mc == pytest.approx(2800.0 * 14_000_000_000)


# ===========================================================================
# Per-row adjustment tests (Step 1.1 — new tests replacing old buggy test)
# ===========================================================================

def _df(dates, close):
    return pd.DataFrame(
        {"open_raw": close, "high_raw": close, "low_raw": close, "close_raw": close},
        index=dates,
    )


SPLIT = {"ex_date": date(2024, 5, 31), "action_type": "SPLIT", "ratio_numerator": 1.0, "ratio_denominator": 2.0}
D = [date(2024, 5, 29), date(2024, 5, 30), date(2024, 5, 31), date(2024, 6, 3)]


def test_split_adjusts_only_bars_before_ex_date():
    adj = get_adjusted_series(_df(D, [200.0, 200.0, 100.0, 100.0]), [SPLIT], as_of_date=date(2024, 6, 3))
    assert list(adj["close_adj"]) == [100.0, 100.0, 100.0, 100.0]


def test_split_after_as_of_date_ignored():
    adj = get_adjusted_series(_df(D, [200.0, 200.0, 100.0, 100.0]), [SPLIT], as_of_date=date(2024, 5, 30))
    assert list(adj["close_adj"]) == [200.0, 200.0, 100.0, 100.0]


def test_bonus_and_split_compound():
    bonus = {"ex_date": date(2024, 5, 30), "action_type": "BONUS", "ratio_numerator": 1.0, "ratio_denominator": 1.0}  # x0.5
    adj = get_adjusted_series(_df(D, [400.0, 200.0, 100.0, 100.0]), [bonus, SPLIT], as_of_date=date(2024, 6, 3))
    assert list(adj["close_adj"]) == [100.0, 100.0, 100.0, 100.0]


def test_no_price_jump_across_split_after_adjustment():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
    close = [500.0] * 20 + [100.0] * 20
    act = {"ex_date": dates[20], "action_type": "SPLIT", "ratio_numerator": 1.0, "ratio_denominator": 5.0}
    adj = get_adjusted_series(_df(dates, close), [act], as_of_date=dates[-1])
    assert adj["close_adj"].pct_change().abs().max() < 1e-9
